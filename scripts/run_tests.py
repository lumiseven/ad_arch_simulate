#!/usr/bin/env python3
"""
测试运行脚本
提供多种测试运行选项，包括单元测试、集成测试、性能测试等
"""

import sys
import os
import subprocess
import argparse
import time
from pathlib import Path
from typing import List, Dict, Optional

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.utils import setup_logging


class TestRunner:
    """测试运行器"""
    
    def __init__(self):
        self.logger = setup_logging("test-runner")
        self.project_root = Path(__file__).parent.parent
        
    def run_command(self, cmd: List[str], cwd: Optional[Path] = None) -> tuple:
        """运行命令并返回结果"""
        if cwd is None:
            cwd = self.project_root
            
        self.logger.info(f"执行命令: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=300  # 5分钟超时
            )
            
            return result.returncode, result.stdout, result.stderr
            
        except subprocess.TimeoutExpired:
            self.logger.error("命令执行超时")
            return 1, "", "Command timed out"
        except Exception as e:
            self.logger.error(f"命令执行失败: {e}")
            return 1, "", str(e)
    
    def check_dependencies(self) -> bool:
        """检查测试依赖"""
        self.logger.info("🔍 检查测试依赖...")
        
        # 检查 pytest
        returncode, _, _ = self.run_command([sys.executable, "-m", "pytest", "--version"])
        if returncode != 0:
            self.logger.error("❌ pytest 未安装")
            return False
        
        # 检查 pytest-asyncio
        returncode, _, _ = self.run_command([sys.executable, "-c", "import pytest_asyncio"])
        if returncode != 0:
            self.logger.error("❌ pytest-asyncio 未安装")
            return False
        
        # 检查 pytest-cov
        returncode, _, _ = self.run_command([sys.executable, "-c", "import pytest_cov"])
        if returncode != 0:
            self.logger.warning("⚠️ pytest-cov 未安装，无法生成覆盖率报告")
        
        self.logger.info("✅ 测试依赖检查完成")
        return True
    
    def run_unit_tests(self, verbose: bool = False, coverage: bool = False) -> bool:
        """运行单元测试"""
        self.logger.info("🧪 运行单元测试...")
        
        cmd = [sys.executable, "-m", "pytest"]
        
        # 添加测试文件模式
        test_patterns = [
            "tests/test_shared_*.py",
            "tests/test_*_service.py"
        ]
        cmd.extend(test_patterns)
        
        # 添加选项
        if verbose:
            cmd.append("-v")
        
        if coverage:
            cmd.extend([
                "--cov=shared",
                "--cov=server", 
                "--cov-report=term-missing",
                "--cov-report=html:htmlcov"
            ])
        
        # 添加其他有用的选项
        cmd.extend([
            "--tb=short",
            "--strict-markers",
            "-x"  # 遇到第一个失败就停止
        ])
        
        returncode, stdout, stderr = self.run_command(cmd)
        
        if returncode == 0:
            self.logger.info("✅ 单元测试通过")
            return True
        else:
            self.logger.error("❌ 单元测试失败")
            self.logger.error(f"STDOUT: {stdout}")
            self.logger.error(f"STDERR: {stderr}")
            return False
    
    def run_integration_tests(self, verbose: bool = False) -> bool:
        """运行集成测试"""
        self.logger.info("🔗 运行集成测试...")
        
        cmd = [sys.executable, "-m", "pytest"]
        
        # 集成测试文件
        integration_tests = [
            "tests/test_service_communication.py",
            "tests/test_database_integration.py",
            "tests/test_rtb_demo_flow.py"
        ]
        cmd.extend(integration_tests)
        
        if verbose:
            cmd.append("-v")
        
        cmd.extend([
            "--tb=short",
            "-x"
        ])
        
        returncode, stdout, stderr = self.run_command(cmd)
        
        if returncode == 0:
            self.logger.info("✅ 集成测试通过")
            return True
        else:
            self.logger.error("❌ 集成测试失败")
            self.logger.error(f"STDOUT: {stdout}")
            self.logger.error(f"STDERR: {stderr}")
            return False
    
    def run_system_tests(self, verbose: bool = False) -> bool:
        """运行系统测试"""
        self.logger.info("🏗️ 运行系统测试...")
        
        cmd = [sys.executable, "-m", "pytest"]
        
        # 系统测试文件
        system_tests = [
            "tests/test_system_integration.py"
        ]
        cmd.extend(system_tests)
        
        if verbose:
            cmd.append("-v")
        
        cmd.extend([
            "--tb=short",
            "-m", "not slow"  # 跳过慢速测试
        ])
        
        returncode, stdout, stderr = self.run_command(cmd)
        
        if returncode == 0:
            self.logger.info("✅ 系统测试通过")
            return True
        else:
            self.logger.error("❌ 系统测试失败")
            self.logger.error(f"STDOUT: {stdout}")
            self.logger.error(f"STDERR: {stderr}")
            return False
    
    def run_performance_tests(self, verbose: bool = False) -> bool:
        """运行性能测试"""
        self.logger.info("⚡ 运行性能测试...")
        
        cmd = [sys.executable, "-m", "pytest"]
        
        # 性能测试
        cmd.extend([
            "tests/test_system_integration.py::TestSystemLoadTesting",
            "-m", "slow"
        ])
        
        if verbose:
            cmd.append("-v")
        
        cmd.extend([
            "--tb=short",
            "--durations=10"  # 显示最慢的10个测试
        ])
        
        returncode, stdout, stderr = self.run_command(cmd)
        
        if returncode == 0:
            self.logger.info("✅ 性能测试通过")
            return True
        else:
            self.logger.error("❌ 性能测试失败")
            self.logger.error(f"STDOUT: {stdout}")
            self.logger.error(f"STDERR: {stderr}")
            return False
    
    def run_all_tests(self, verbose: bool = False, coverage: bool = False) -> bool:
        """运行所有测试"""
        self.logger.info("🎯 运行所有测试...")
        
        cmd = [sys.executable, "-m", "pytest", "tests/"]
        
        if verbose:
            cmd.append("-v")
        
        if coverage:
            cmd.extend([
                "--cov=shared",
                "--cov=server",
                "--cov-report=term-missing",
                "--cov-report=html:htmlcov",
                "--cov-report=xml:coverage.xml"
            ])
        
        cmd.extend([
            "--tb=short",
            "--strict-markers"
        ])
        
        returncode, stdout, stderr = self.run_command(cmd)
        
        if returncode == 0:
            self.logger.info("✅ 所有测试通过")
            return True
        else:
            self.logger.error("❌ 部分测试失败")
            self.logger.error(f"STDOUT: {stdout}")
            self.logger.error(f"STDERR: {stderr}")
            return False
    
    def run_specific_test(self, test_path: str, verbose: bool = False) -> bool:
        """运行特定测试"""
        self.logger.info(f"🎯 运行特定测试: {test_path}")
        
        cmd = [sys.executable, "-m", "pytest", test_path]
        
        if verbose:
            cmd.append("-v")
        
        cmd.extend([
            "--tb=short"
        ])
        
        returncode, stdout, stderr = self.run_command(cmd)
        
        if returncode == 0:
            self.logger.info("✅ 测试通过")
            return True
        else:
            self.logger.error("❌ 测试失败")
            self.logger.error(f"STDOUT: {stdout}")
            self.logger.error(f"STDERR: {stderr}")
            return False
    
    def run_code_quality_checks(self) -> bool:
        """运行代码质量检查"""
        self.logger.info("🔍 运行代码质量检查...")
        
        checks_passed = True
        
        # 检查代码格式 (black)
        self.logger.info("检查代码格式...")
        returncode, _, stderr = self.run_command([
            sys.executable, "-m", "black", "--check", "--diff", "."
        ])
        
        if returncode != 0:
            self.logger.warning("⚠️ 代码格式检查失败")
            self.logger.info("运行 'black .' 来修复格式问题")
            checks_passed = False
        else:
            self.logger.info("✅ 代码格式检查通过")
        
        # 检查导入排序 (isort)
        self.logger.info("检查导入排序...")
        returncode, _, stderr = self.run_command([
            sys.executable, "-m", "isort", "--check-only", "--diff", "."
        ])
        
        if returncode != 0:
            self.logger.warning("⚠️ 导入排序检查失败")
            self.logger.info("运行 'isort .' 来修复导入排序")
            checks_passed = False
        else:
            self.logger.info("✅ 导入排序检查通过")
        
        # 代码检查 (flake8)
        self.logger.info("运行代码检查...")
        returncode, stdout, stderr = self.run_command([
            sys.executable, "-m", "flake8", "shared/", "server/", "scripts/", "tests/"
        ])
        
        if returncode != 0:
            self.logger.warning("⚠️ 代码检查发现问题")
            self.logger.warning(f"Flake8 输出: {stdout}")
            checks_passed = False
        else:
            self.logger.info("✅ 代码检查通过")
        
        return checks_passed
    
    def generate_test_report(self) -> Dict:
        """生成测试报告"""
        self.logger.info("📊 生成测试报告...")
        
        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tests": {}
        }
        
        # 运行各类测试并记录结果
        test_types = [
            ("unit", self.run_unit_tests),
            ("integration", self.run_integration_tests),
            ("system", self.run_system_tests)
        ]
        
        for test_type, test_func in test_types:
            start_time = time.time()
            success = test_func(verbose=False)
            end_time = time.time()
            
            report["tests"][test_type] = {
                "success": success,
                "duration": end_time - start_time
            }
        
        # 保存报告
        report_file = self.project_root / "test_report.json"
        import json
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        self.logger.info(f"📄 测试报告已保存: {report_file}")
        
        return report
    
    def clean_test_artifacts(self):
        """清理测试产生的文件"""
        self.logger.info("🧹 清理测试文件...")
        
        # 清理的文件和目录
        cleanup_patterns = [
            "**/__pycache__",
            "**/*.pyc",
            ".pytest_cache",
            "htmlcov",
            "coverage.xml",
            ".coverage",
            "test_report.json"
        ]
        
        import shutil
        from glob import glob
        
        for pattern in cleanup_patterns:
            for path in glob(str(self.project_root / pattern), recursive=True):
                path_obj = Path(path)
                try:
                    if path_obj.is_dir():
                        shutil.rmtree(path_obj)
                        self.logger.info(f"删除目录: {path_obj}")
                    else:
                        path_obj.unlink()
                        self.logger.info(f"删除文件: {path_obj}")
                except Exception as e:
                    self.logger.warning(f"无法删除 {path_obj}: {e}")
        
        self.logger.info("✅ 清理完成")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="测试运行脚本")
    parser.add_argument(
        "test_type",
        choices=["unit", "integration", "system", "performance", "all", "specific", "quality", "report", "clean"],
        help="要运行的测试类型"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细输出"
    )
    parser.add_argument(
        "--coverage", "-c",
        action="store_true",
        help="生成覆盖率报告"
    )
    parser.add_argument(
        "--test-path",
        help="特定测试文件路径 (用于 specific 类型)"
    )
    
    args = parser.parse_args()
    
    runner = TestRunner()
    
    # 检查依赖
    if not runner.check_dependencies():
        sys.exit(1)
    
    success = True
    
    try:
        if args.test_type == "unit":
            success = runner.run_unit_tests(args.verbose, args.coverage)
        elif args.test_type == "integration":
            success = runner.run_integration_tests(args.verbose)
        elif args.test_type == "system":
            success = runner.run_system_tests(args.verbose)
        elif args.test_type == "performance":
            success = runner.run_performance_tests(args.verbose)
        elif args.test_type == "all":
            success = runner.run_all_tests(args.verbose, args.coverage)
        elif args.test_type == "specific":
            if not args.test_path:
                print("错误: --test-path 参数是必需的")
                sys.exit(1)
            success = runner.run_specific_test(args.test_path, args.verbose)
        elif args.test_type == "quality":
            success = runner.run_code_quality_checks()
        elif args.test_type == "report":
            report = runner.generate_test_report()
            print(f"测试报告: {report}")
        elif args.test_type == "clean":
            runner.clean_test_artifacts()
            return
        
        if success:
            print("🎉 测试成功完成!")
            sys.exit(0)
        else:
            print("❌ 测试失败")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n测试被用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"测试运行出错: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()