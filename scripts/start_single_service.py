#!/usr/bin/env python3
"""
单个服务启动脚本
用于启动指定的单个服务，支持开发和生产模式
"""

import sys
import os
import argparse
import asyncio
import signal
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.utils import setup_logging
from shared.config import get_config


class SingleServiceManager:
    """单个服务管理器"""
    
    def __init__(self, service_name: str, debug: bool = False):
        self.service_name = service_name
        self.debug = debug
        self.logger = setup_logging(f"{service_name}-manager")
        self.config = get_config(service_name)
        self.shutdown_requested = False
        
    def setup_signal_handlers(self):
        """设置信号处理器"""
        def signal_handler(signum, frame):
            self.logger.info(f"接收到信号 {signum}，开始关闭服务...")
            self.shutdown_requested = True
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def start_service(self):
        """启动服务"""
        self.logger.info(f"🚀 启动 {self.service_name} 服务...")
        
        # 根据服务名称导入对应的模块
        service_module_map = {
            "ad-management": "server.ad-management.main",
            "dsp": "server.dsp.main",
            "ssp": "server.ssp.main", 
            "ad-exchange": "server.ad-exchange.main",
            "dmp": "server.dmp.main"
        }
        
        if self.service_name not in service_module_map:
            raise ValueError(f"未知的服务名称: {self.service_name}")
        
        module_path = service_module_map[self.service_name]
        
        try:
            # 动态导入服务模块
            import importlib
            service_module = importlib.import_module(module_path)
            
            # 获取 FastAPI 应用
            if hasattr(service_module, 'app'):
                app = service_module.app
                
                # 启动服务
                import uvicorn
                
                config = uvicorn.Config(
                    app,
                    host=self.config.service.host,
                    port=self.config.service.port,
                    log_level="debug" if self.debug else "info",
                    reload=self.debug,
                    access_log=True
                )
                
                server = uvicorn.Server(config)
                
                self.logger.info(f"✅ {self.service_name} 服务启动成功")
                self.logger.info(f"📍 服务地址: http://{self.config.service.host}:{self.config.service.port}")
                self.logger.info(f"📚 API 文档: http://{self.config.service.host}:{self.config.service.port}/docs")
                
                # 运行服务
                await server.serve()
                
            else:
                raise AttributeError(f"服务模块 {module_path} 没有 'app' 属性")
                
        except Exception as e:
            self.logger.error(f"❌ 启动 {self.service_name} 服务失败: {e}")
            raise
    
    async def run(self):
        """运行服务管理器"""
        self.setup_signal_handlers()
        
        try:
            await self.start_service()
        except KeyboardInterrupt:
            self.logger.info("用户请求关闭服务")
        except Exception as e:
            self.logger.error(f"服务运行出错: {e}")
            return 1
        
        return 0


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="启动单个广告系统服务")
    parser.add_argument(
        "service", 
        choices=["ad-management", "dsp", "ssp", "ad-exchange", "dmp"],
        help="要启动的服务名称"
    )
    parser.add_argument(
        "--debug", 
        action="store_true",
        help="启用调试模式"
    )
    parser.add_argument(
        "--host",
        default=None,
        help="服务监听地址"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="服务监听端口"
    )
    
    args = parser.parse_args()
    
    # 设置环境变量
    if args.host:
        os.environ["HOST"] = args.host
    if args.port:
        os.environ["PORT"] = str(args.port)
    if args.debug:
        os.environ["DEBUG"] = "true"
        os.environ["LOG_LEVEL"] = "DEBUG"
    
    # 创建服务管理器
    manager = SingleServiceManager(args.service, args.debug)
    
    # 运行服务
    try:
        exit_code = asyncio.run(manager.run())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n服务已停止")
        sys.exit(0)


if __name__ == "__main__":
    main()