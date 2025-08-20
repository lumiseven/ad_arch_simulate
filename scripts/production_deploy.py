#!/usr/bin/env python3
"""
生产环境部署脚本
用于生产环境的服务部署、配置和监控
"""

import sys
import os
import json
import subprocess
import time
import argparse
from pathlib import Path
from typing import Dict, List, Optional

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.utils import setup_logging
from shared.config import get_config


class ProductionDeployManager:
    """生产环境部署管理器"""
    
    def __init__(self, config_file: Optional[str] = None):
        self.logger = setup_logging("production-deploy")
        self.config_file = config_file or "config.json"
        self.services = ["ad-management", "dsp", "ssp", "ad-exchange", "dmp"]
        self.processes: Dict[str, subprocess.Popen] = {}
        
    def load_production_config(self) -> Dict:
        """加载生产环境配置"""
        config_path = Path(self.config_file)
        
        if not config_path.exists():
            self.logger.warning(f"配置文件 {config_path} 不存在，使用默认配置")
            return self.get_default_production_config()
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            self.logger.info(f"✅ 加载生产配置: {config_path}")
            return config
        except Exception as e:
            self.logger.error(f"❌ 加载配置文件失败: {e}")
            return self.get_default_production_config()
    
    def get_default_production_config(self) -> Dict:
        """获取默认生产配置"""
        return {
            "environment": "production",
            "services": {
                "ad-management": {"port": 8001, "workers": 2},
                "dsp": {"port": 8002, "workers": 2},
                "ssp": {"port": 8003, "workers": 2},
                "ad-exchange": {"port": 8004, "workers": 4},
                "dmp": {"port": 8005, "workers": 2}
            },
            "database": {
                "url": "sqlite+aiosqlite:///./data/ad_system.db",
                "pool_size": 10,
                "echo": False
            },
            "logging": {
                "level": "INFO",
                "file": "logs/production.log"
            },
            "monitoring": {
                "enabled": True,
                "check_interval": 30
            }
        }
    
    def setup_production_environment(self):
        """设置生产环境"""
        self.logger.info("🔧 设置生产环境...")
        
        # 创建必要的目录
        directories = ["data", "logs", "backups", "config"]
        for directory in directories:
            Path(directory).mkdir(exist_ok=True)
            self.logger.info(f"✅ 创建目录: {directory}")
        
        # 设置环境变量
        production_env = {
            "ENVIRONMENT": "production",
            "DEBUG": "false",
            "LOG_LEVEL": "INFO",
            "DATABASE_ECHO": "false"
        }
        
        for key, value in production_env.items():
            os.environ[key] = value
        
        self.logger.info("✅ 生产环境设置完成")
    
    def check_system_requirements(self) -> bool:
        """检查系统要求"""
        self.logger.info("🔍 检查系统要求...")
        
        requirements_met = True
        
        # 检查 Python 版本
        python_version = sys.version_info
        if python_version < (3, 9):
            self.logger.error(f"❌ Python 版本过低: {python_version.major}.{python_version.minor}")
            requirements_met = False
        else:
            self.logger.info(f"✅ Python 版本: {python_version.major}.{python_version.minor}")
        
        # 检查磁盘空间
        try:
            import shutil
            disk_usage = shutil.disk_usage(".")
            free_gb = disk_usage.free / (1024**3)
            
            if free_gb < 1:  # 至少需要 1GB 空间
                self.logger.error(f"❌ 磁盘空间不足: {free_gb:.2f}GB")
                requirements_met = False
            else:
                self.logger.info(f"✅ 可用磁盘空间: {free_gb:.2f}GB")
        except Exception as e:
            self.logger.warning(f"⚠️ 无法检查磁盘空间: {e}")
        
        # 检查端口可用性
        import socket
        for service in self.services:
            port = 8001 + ["ad-management", "dsp", "ssp", "ad-exchange", "dmp"].index(service)
            
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                result = s.connect_ex(('localhost', port))
                if result == 0:
                    self.logger.warning(f"⚠️ 端口 {port} 已被占用 ({service})")
                else:
                    self.logger.info(f"✅ 端口 {port} 可用 ({service})")
        
        return requirements_met
    
    def backup_existing_data(self):
        """备份现有数据"""
        self.logger.info("💾 备份现有数据...")
        
        backup_dir = Path("backups") / f"backup_{int(time.time())}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # 备份数据库
        db_files = ["ad_system.db", "ad_system.db-shm", "ad_system.db-wal"]
        for db_file in db_files:
            db_path = Path(db_file)
            if db_path.exists():
                import shutil
                shutil.copy2(db_path, backup_dir / db_file)
                self.logger.info(f"✅ 备份数据库文件: {db_file}")
        
        # 备份配置文件
        config_files = ["config.json", ".env"]
        for config_file in config_files:
            config_path = Path(config_file)
            if config_path.exists():
                import shutil
                shutil.copy2(config_path, backup_dir / config_file)
                self.logger.info(f"✅ 备份配置文件: {config_file}")
        
        self.logger.info(f"✅ 数据备份完成: {backup_dir}")
    
    def start_service_production(self, service_name: str, config: Dict) -> subprocess.Popen:
        """启动生产环境服务"""
        service_config = config["services"].get(service_name, {})
        port = service_config.get("port", 8001)
        workers = service_config.get("workers", 2)
        
        # 构建启动命令
        service_module = f"server.{service_name.replace('-', '_')}.main:app"
        
        cmd = [
            sys.executable, "-m", "uvicorn",
            service_module,
            "--host", "0.0.0.0",
            "--port", str(port),
            "--workers", str(workers),
            "--log-level", "info",
            "--access-log",
            "--no-use-colors"
        ]
        
        self.logger.info(f"🚀 启动生产服务: {service_name} (端口: {port}, 工作进程: {workers})")
        
        try:
            # 设置环境变量
            env = os.environ.copy()
            env.update({
                "SERVICE_NAME": service_name,
                "PORT": str(port),
                "WORKERS": str(workers)
            })
            
            # 启动进程
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env
            )
            
            # 等待服务启动
            time.sleep(2)
            
            if process.poll() is None:  # 进程仍在运行
                self.logger.info(f"✅ {service_name} 服务启动成功 (PID: {process.pid})")
                return process
            else:
                stdout, stderr = process.communicate()
                self.logger.error(f"❌ {service_name} 服务启动失败")
                self.logger.error(f"STDOUT: {stdout.decode()}")
                self.logger.error(f"STDERR: {stderr.decode()}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ 启动 {service_name} 服务时出错: {e}")
            return None
    
    def start_all_services(self, config: Dict):
        """启动所有服务"""
        self.logger.info("🚀 启动所有生产服务...")
        
        # 按依赖顺序启动服务
        service_order = ["dmp", "ad-management", "dsp", "ssp", "ad-exchange"]
        
        for service_name in service_order:
            process = self.start_service_production(service_name, config)
            if process:
                self.processes[service_name] = process
                time.sleep(3)  # 等待服务完全启动
            else:
                self.logger.error(f"❌ 无法启动 {service_name} 服务")
                return False
        
        self.logger.info(f"✅ 所有服务启动完成 ({len(self.processes)} 个服务)")
        return True
    
    def health_check_all_services(self) -> Dict[str, bool]:
        """检查所有服务健康状态"""
        self.logger.info("🔍 检查所有服务健康状态...")
        
        health_status = {}
        
        for service_name in self.services:
            port = 8001 + self.services.index(service_name)
            
            try:
                import httpx
                with httpx.Client(timeout=10.0) as client:
                    response = client.get(f"http://localhost:{port}/health")
                    
                if response.status_code == 200:
                    health_status[service_name] = True
                    self.logger.info(f"✅ {service_name} 服务健康")
                else:
                    health_status[service_name] = False
                    self.logger.warning(f"⚠️ {service_name} 服务状态异常: {response.status_code}")
                    
            except Exception as e:
                health_status[service_name] = False
                self.logger.error(f"❌ {service_name} 服务健康检查失败: {e}")
        
        healthy_count = sum(health_status.values())
        total_count = len(health_status)
        
        self.logger.info(f"📊 服务健康状态: {healthy_count}/{total_count} 健康")
        
        return health_status
    
    def setup_monitoring(self, config: Dict):
        """设置监控"""
        if not config.get("monitoring", {}).get("enabled", False):
            self.logger.info("⏭️ 监控未启用，跳过设置")
            return
        
        self.logger.info("📊 设置生产监控...")
        
        # 创建监控脚本
        monitor_script = """#!/bin/bash
# 生产环境监控脚本

LOG_FILE="logs/monitor.log"
CHECK_INTERVAL=30

while true; do
    echo "$(date): 开始健康检查" >> $LOG_FILE
    
    # 检查所有服务
    for port in 8001 8002 8003 8004 8005; do
        if curl -f -s http://localhost:$port/health > /dev/null; then
            echo "$(date): 端口 $port 服务正常" >> $LOG_FILE
        else
            echo "$(date): 警告 - 端口 $port 服务异常" >> $LOG_FILE
        fi
    done
    
    sleep $CHECK_INTERVAL
done
"""
        
        monitor_path = Path("scripts/monitor.sh")
        with open(monitor_path, 'w') as f:
            f.write(monitor_script)
        
        # 设置执行权限
        os.chmod(monitor_path, 0o755)
        
        self.logger.info(f"✅ 监控脚本创建: {monitor_path}")
    
    def create_systemd_service(self):
        """创建 systemd 服务文件"""
        self.logger.info("⚙️ 创建 systemd 服务文件...")
        
        service_content = f"""[Unit]
Description=Ad System Architecture Demo
After=network.target

[Service]
Type=simple
User={os.getenv('USER', 'app')}
WorkingDirectory={Path.cwd()}
ExecStart={sys.executable} {Path(__file__).parent / 'start_services.py'}
Restart=always
RestartSec=10
Environment=ENVIRONMENT=production
Environment=LOG_LEVEL=INFO

[Install]
WantedBy=multi-user.target
"""
        
        service_file = Path("ad-system.service")
        with open(service_file, 'w') as f:
            f.write(service_content)
        
        self.logger.info(f"✅ systemd 服务文件创建: {service_file}")
        self.logger.info("💡 安装提示:")
        self.logger.info(f"   sudo cp {service_file} /etc/systemd/system/")
        self.logger.info("   sudo systemctl enable ad-system")
        self.logger.info("   sudo systemctl start ad-system")
    
    def stop_all_services(self):
        """停止所有服务"""
        self.logger.info("🛑 停止所有服务...")
        
        for service_name, process in self.processes.items():
            try:
                self.logger.info(f"停止 {service_name} 服务...")
                process.terminate()
                
                # 等待优雅关闭
                try:
                    process.wait(timeout=10)
                    self.logger.info(f"✅ {service_name} 服务已停止")
                except subprocess.TimeoutExpired:
                    # 强制终止
                    process.kill()
                    process.wait()
                    self.logger.warning(f"⚠️ {service_name} 服务被强制终止")
                    
            except Exception as e:
                self.logger.error(f"❌ 停止 {service_name} 服务时出错: {e}")
        
        self.processes.clear()
        self.logger.info("✅ 所有服务已停止")
    
    def deploy(self, skip_backup: bool = False, skip_checks: bool = False):
        """执行完整部署"""
        self.logger.info("🚀 开始生产环境部署...")
        
        try:
            # 1. 检查系统要求
            if not skip_checks and not self.check_system_requirements():
                self.logger.error("❌ 系统要求检查失败")
                return False
            
            # 2. 备份现有数据
            if not skip_backup:
                self.backup_existing_data()
            
            # 3. 设置生产环境
            self.setup_production_environment()
            
            # 4. 加载配置
            config = self.load_production_config()
            
            # 5. 启动服务
            if not self.start_all_services(config):
                self.logger.error("❌ 服务启动失败")
                return False
            
            # 6. 健康检查
            time.sleep(5)  # 等待服务完全启动
            health_status = self.health_check_all_services()
            
            healthy_count = sum(health_status.values())
            if healthy_count < len(self.services) * 0.8:  # 至少 80% 服务健康
                self.logger.error(f"❌ 健康服务数量不足: {healthy_count}/{len(self.services)}")
                return False
            
            # 7. 设置监控
            self.setup_monitoring(config)
            
            # 8. 创建 systemd 服务
            self.create_systemd_service()
            
            self.logger.info("🎉 生产环境部署完成!")
            self.logger.info("📍 服务访问地址:")
            for i, service in enumerate(self.services):
                port = 8001 + i
                self.logger.info(f"   {service}: http://localhost:{port}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 部署过程中出错: {e}")
            self.stop_all_services()
            return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="生产环境部署脚本")
    parser.add_argument(
        "--config",
        default="config.json",
        help="配置文件路径"
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="跳过数据备份"
    )
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help="跳过系统要求检查"
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="停止所有服务"
    )
    
    args = parser.parse_args()
    
    # 创建部署管理器
    manager = ProductionDeployManager(args.config)
    
    try:
        if args.stop:
            manager.stop_all_services()
        else:
            success = manager.deploy(args.skip_backup, args.skip_checks)
            if not success:
                sys.exit(1)
                
    except KeyboardInterrupt:
        print("\n部署被用户中断")
        manager.stop_all_services()
        sys.exit(0)
    except Exception as e:
        print(f"部署失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()