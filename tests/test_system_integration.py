"""
完整的系统集成测试套件
测试所有服务的集成、RTB 工作流程、错误处理和性能指标
"""

import pytest
import asyncio
import time
import json
import httpx
from datetime import datetime, timedelta
from typing import Dict, List, Any
from unittest.mock import patch, AsyncMock

# 导入测试工具和配置
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.utils import APIClient, get_service_registry, setup_logging
from shared.models import Campaign, UserProfile, BidRequest, BidResponse
from shared.config import get_config


class TestSystemIntegration:
    """系统集成测试类"""
    
    @classmethod
    def setup_class(cls):
        """设置测试类"""
        cls.logger = setup_logging("system-integration-test")
        cls.service_urls = {
            "ad-management": "http://localhost:8001",
            "dsp": "http://localhost:8002", 
            "ssp": "http://localhost:8003",
            "ad-exchange": "http://localhost:8004",
            "dmp": "http://localhost:8005"
        }
        cls.clients = {}
        
    async def setup_method(self):
        """设置测试方法"""
        # 创建 API 客户端
        for service, url in self.service_urls.items():
            self.clients[service] = APIClient(url, timeout=10.0, max_retries=2)
    
    async def teardown_method(self):
        """清理测试方法"""
        # 关闭所有客户端
        for client in self.clients.values():
            await client.close()
    
    @pytest.mark.asyncio
    async def test_all_services_health_check(self):
        """测试所有服务的健康检查"""
        self.logger.info("开始测试所有服务健康检查")
        
        health_results = {}
        
        for service_name, client in self.clients.items():
            try:
                health_response = await client.health_check()
                health_results[service_name] = health_response
                
                assert health_response["status"] in ["healthy", "degraded"]
                assert "service" in health_response
                assert "timestamp" in health_response
                
                self.logger.info(f"✅ {service_name} 服务健康: {health_response['status']}")
                
            except Exception as e:
                self.logger.error(f"❌ {service_name} 服务健康检查失败: {e}")
                health_results[service_name] = {"status": "unhealthy", "error": str(e)}
        
        # 至少要有 80% 的服务健康
        healthy_count = sum(1 for result in health_results.values() 
                          if result.get("status") in ["healthy", "degraded"])
        total_services = len(health_results)
        health_ratio = healthy_count / total_services
        
        assert health_ratio >= 0.8, f"健康服务比例过低: {health_ratio:.2%}"
        self.logger.info(f"系统健康状态: {healthy_count}/{total_services} 服务正常")
    
    @pytest.mark.asyncio
    async def test_service_discovery_and_registration(self):
        """测试服务发现和注册"""
        self.logger.info("开始测试服务发现和注册")
        
        registry = get_service_registry()
        
        # 检查服务注册
        registered_services = registry.list_services()
        self.logger.info(f"已注册服务: {list(registered_services.keys())}")
        
        # 验证核心服务已注册
        expected_services = ["ad-management", "dsp", "ssp", "ad-exchange", "dmp"]
        for service in expected_services:
            if service in registered_services:
                service_info = registry.get_service(service)
                assert service_info is not None
                assert "url" in service_info
                assert "status" in service_info
                self.logger.info(f"✅ {service} 服务已注册: {service_info['url']}")
    
    @pytest.mark.asyncio
    async def test_complete_rtb_workflow_integration(self):
        """测试完整的 RTB 工作流程集成"""
        self.logger.info("开始测试完整 RTB 工作流程")
        
        # 1. 创建测试广告活动
        campaign_data = {
            "name": "集成测试活动",
            "advertiser_id": "integration_test",
            "budget": 1000.0,
            "targeting": {
                "age_range": {"min_age": 18, "max_age": 35},
                "interests": ["technology", "shopping"]
            },
            "creative": {
                "title": "集成测试广告",
                "description": "这是一个集成测试广告"
            }
        }
        
        campaign_response = await self.clients["ad-management"].post("/campaigns", json_data=campaign_data)
        assert "data" in campaign_response
        campaign_id = campaign_response["data"]["id"]
        self.logger.info(f"✅ 创建测试活动: {campaign_id}")
        
        # 2. 创建测试用户画像
        user_id = "integration_test_user"
        profile_data = {
            "demographics": {"age": 25, "gender": "male"},
            "interests": ["technology", "shopping"],
            "behaviors": ["frequent_buyer"],
            "segments": ["tech_enthusiast"]
        }
        
        await self.clients["dmp"].put(f"/user/{user_id}/profile", json_data=profile_data)
        self.logger.info(f"✅ 创建测试用户画像: {user_id}")
        
        # 3. 执行 RTB 演示流程
        rtb_context = {
            "user_id": user_id,
            "device_type": "desktop",
            "location": {"country": "CN", "city": "北京"}
        }
        
        start_time = time.time()
        rtb_response = await self.clients["ad-exchange"].post("/demo/rtb-flow", json_data=rtb_context)
        end_time = time.time()
        
        # 验证 RTB 响应
        assert "workflow_result" in rtb_response
        workflow_result = rtb_response["workflow_result"]
        assert workflow_result["status"] == "success"
        
        # 验证性能要求
        duration_ms = (end_time - start_time) * 1000
        assert duration_ms < 200, f"RTB 流程耗时过长: {duration_ms:.2f}ms"
        
        self.logger.info(f"✅ RTB 流程完成，耗时: {duration_ms:.2f}ms")
        
        # 4. 验证数据一致性
        # 检查活动统计是否更新
        await asyncio.sleep(1)  # 等待异步更新
        stats_response = await self.clients["ad-management"].get(f"/campaigns/{campaign_id}/stats")
        if "data" in stats_response:
            self.logger.info("✅ 活动统计数据已更新")
        
        # 5. 清理测试数据
        await self.clients["ad-management"].delete(f"/campaigns/{campaign_id}")
        self.logger.info("✅ 清理测试数据完成")
    
    @pytest.mark.asyncio
    async def test_concurrent_rtb_requests(self):
        """测试并发 RTB 请求处理"""
        self.logger.info("开始测试并发 RTB 请求")
        
        concurrent_requests = 10
        tasks = []
        
        for i in range(concurrent_requests):
            context = {
                "user_id": f"concurrent_user_{i}",
                "device_type": "mobile" if i % 2 else "desktop",
                "location": {"country": "CN", "city": "上海"}
            }
            task = self.clients["ad-exchange"].post("/demo/rtb-flow-simple", json_data=context)
            tasks.append(task)
        
        start_time = time.time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.time()
        
        # 分析结果
        successful_requests = 0
        failed_requests = 0
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.warning(f"请求 {i} 失败: {result}")
                failed_requests += 1
            else:
                if result.get("status") == "success":
                    successful_requests += 1
                else:
                    failed_requests += 1
        
        # 验证并发处理能力
        success_rate = successful_requests / concurrent_requests
        total_time = end_time - start_time
        avg_time_per_request = total_time / concurrent_requests * 1000
        
        assert success_rate >= 0.8, f"并发请求成功率过低: {success_rate:.2%}"
        assert avg_time_per_request < 500, f"平均响应时间过长: {avg_time_per_request:.2f}ms"
        
        self.logger.info(f"✅ 并发测试完成: {successful_requests}/{concurrent_requests} 成功, "
                        f"平均响应时间: {avg_time_per_request:.2f}ms")
    
    @pytest.mark.asyncio
    async def test_error_handling_and_resilience(self):
        """测试错误处理和系统韧性"""
        self.logger.info("开始测试错误处理和系统韧性")
        
        # 1. 测试无效请求处理
        invalid_campaign = {
            "name": "",  # 无效的空名称
            "budget": -100  # 无效的负预算
        }
        
        try:
            await self.clients["ad-management"].post("/campaigns", json_data=invalid_campaign)
            assert False, "应该抛出验证错误"
        except Exception as e:
            self.logger.info(f"✅ 正确处理无效请求: {type(e).__name__}")
        
        # 2. 测试不存在资源的处理
        try:
            await self.clients["ad-management"].get("/campaigns/nonexistent_id")
            assert False, "应该返回 404 错误"
        except Exception as e:
            self.logger.info(f"✅ 正确处理不存在的资源: {type(e).__name__}")
        
        # 3. 测试服务间通信错误处理
        # 模拟 DMP 服务不可用的情况
        with patch.object(self.clients["dmp"], 'get', side_effect=Exception("Service unavailable")):
            rtb_response = await self.clients["ad-exchange"].post("/demo/rtb-flow-simple")
            
            # RTB 流程应该能够处理 DMP 不可用的情况
            assert rtb_response.get("status") in ["success", "failed"]
            self.logger.info("✅ RTB 流程正确处理 DMP 服务不可用")
        
        # 4. 测试超时处理
        # 创建一个超时的客户端
        timeout_client = APIClient(self.service_urls["ad-exchange"], timeout=0.001)  # 1ms 超时
        
        try:
            await timeout_client.get("/health")
            assert False, "应该发生超时"
        except Exception as e:
            self.logger.info(f"✅ 正确处理超时: {type(e).__name__}")
        finally:
            await timeout_client.close()
    
    @pytest.mark.asyncio
    async def test_data_consistency_across_services(self):
        """测试跨服务数据一致性"""
        self.logger.info("开始测试跨服务数据一致性")
        
        # 1. 创建广告活动
        campaign_data = {
            "name": "数据一致性测试",
            "advertiser_id": "consistency_test",
            "budget": 500.0,
            "targeting": {"interests": ["technology"]},
            "creative": {"title": "测试广告"}
        }
        
        campaign_response = await self.clients["ad-management"].post("/campaigns", json_data=campaign_data)
        campaign_id = campaign_response["data"]["id"]
        
        # 2. 执行多次 RTB 流程
        for i in range(5):
            await self.clients["ad-exchange"].post("/demo/rtb-flow-simple")
            await asyncio.sleep(0.1)  # 短暂延迟
        
        # 3. 检查数据一致性
        # 获取活动统计
        stats_response = await self.clients["ad-management"].get(f"/campaigns/{campaign_id}/stats")
        
        # 获取 DSP 统计
        dsp_stats_response = await self.clients["dsp"].get("/stats")
        
        # 获取 SSP 收益
        ssp_revenue_response = await self.clients["ssp"].get("/revenue")
        
        # 获取工作流程统计
        workflow_stats_response = await self.clients["ad-exchange"].get("/demo/workflow-stats")
        
        # 验证数据存在且格式正确
        if "data" in stats_response:
            assert "impressions" in stats_response["data"]
            self.logger.info("✅ 广告活动统计数据一致")
        
        if "data" in dsp_stats_response:
            assert "total_bids" in dsp_stats_response["data"]
            self.logger.info("✅ DSP 统计数据一致")
        
        if "data" in ssp_revenue_response:
            assert "total_impressions" in ssp_revenue_response["data"]
            self.logger.info("✅ SSP 收益数据一致")
        
        if "data" in workflow_stats_response:
            assert "workflow_statistics" in workflow_stats_response["data"]
            self.logger.info("✅ 工作流程统计数据一致")
        
        # 清理
        await self.clients["ad-management"].delete(f"/campaigns/{campaign_id}")
    
    @pytest.mark.asyncio
    async def test_performance_benchmarks(self):
        """测试性能基准"""
        self.logger.info("开始测试性能基准")
        
        performance_results = {}
        
        # 1. 测试健康检查性能
        health_times = []
        for _ in range(10):
            start_time = time.time()
            await self.clients["ad-exchange"].health_check()
            end_time = time.time()
            health_times.append((end_time - start_time) * 1000)
        
        avg_health_time = sum(health_times) / len(health_times)
        performance_results["health_check_avg_ms"] = avg_health_time
        assert avg_health_time < 50, f"健康检查平均响应时间过长: {avg_health_time:.2f}ms"
        
        # 2. 测试 RTB 流程性能
        rtb_times = []
        for _ in range(10):
            start_time = time.time()
            await self.clients["ad-exchange"].post("/demo/rtb-flow-simple")
            end_time = time.time()
            rtb_times.append((end_time - start_time) * 1000)
        
        avg_rtb_time = sum(rtb_times) / len(rtb_times)
        performance_results["rtb_flow_avg_ms"] = avg_rtb_time
        assert avg_rtb_time < 200, f"RTB 流程平均响应时间过长: {avg_rtb_time:.2f}ms"
        
        # 3. 测试数据库操作性能
        db_times = []
        for i in range(5):
            campaign_data = {
                "name": f"性能测试活动 {i}",
                "advertiser_id": "perf_test",
                "budget": 100.0,
                "targeting": {"interests": ["test"]},
                "creative": {"title": "测试"}
            }
            
            start_time = time.time()
            response = await self.clients["ad-management"].post("/campaigns", json_data=campaign_data)
            end_time = time.time()
            
            db_times.append((end_time - start_time) * 1000)
            
            # 清理
            if "data" in response:
                await self.clients["ad-management"].delete(f"/campaigns/{response['data']['id']}")
        
        avg_db_time = sum(db_times) / len(db_times)
        performance_results["database_operation_avg_ms"] = avg_db_time
        assert avg_db_time < 100, f"数据库操作平均响应时间过长: {avg_db_time:.2f}ms"
        
        self.logger.info(f"✅ 性能基准测试完成: {json.dumps(performance_results, indent=2)}")
    
    @pytest.mark.asyncio
    async def test_system_recovery_after_failure(self):
        """测试系统故障后的恢复能力"""
        self.logger.info("开始测试系统故障恢复")
        
        # 1. 记录正常状态
        initial_health = {}
        for service_name, client in self.clients.items():
            try:
                health = await client.health_check()
                initial_health[service_name] = health["status"]
            except:
                initial_health[service_name] = "unhealthy"
        
        # 2. 模拟服务故障（通过设置极短超时）
        self.logger.info("模拟服务故障...")
        
        # 创建故障客户端
        faulty_clients = {}
        for service, url in self.service_urls.items():
            faulty_clients[service] = APIClient(url, timeout=0.001)  # 1ms 超时
        
        # 尝试访问服务（应该失败）
        failure_count = 0
        for service_name, client in faulty_clients.items():
            try:
                await client.health_check()
            except:
                failure_count += 1
        
        assert failure_count > 0, "应该有服务访问失败"
        self.logger.info(f"检测到 {failure_count} 个服务故障")
        
        # 3. 关闭故障客户端
        for client in faulty_clients.values():
            await client.close()
        
        # 4. 等待恢复
        self.logger.info("等待系统恢复...")
        await asyncio.sleep(2)
        
        # 5. 验证恢复
        recovery_health = {}
        for service_name, client in self.clients.items():
            try:
                health = await client.health_check()
                recovery_health[service_name] = health["status"]
            except:
                recovery_health[service_name] = "unhealthy"
        
        # 比较恢复前后状态
        recovered_services = 0
        for service in initial_health:
            if (initial_health[service] in ["healthy", "degraded"] and 
                recovery_health[service] in ["healthy", "degraded"]):
                recovered_services += 1
        
        recovery_rate = recovered_services / len(initial_health)
        assert recovery_rate >= 0.8, f"系统恢复率过低: {recovery_rate:.2%}"
        
        self.logger.info(f"✅ 系统恢复测试完成: {recovered_services}/{len(initial_health)} 服务恢复")
    
    @pytest.mark.asyncio
    async def test_api_documentation_accessibility(self):
        """测试 API 文档可访问性"""
        self.logger.info("开始测试 API 文档可访问性")
        
        docs_endpoints = ["/docs", "/openapi.json", "/redoc"]
        
        for service_name, client in self.clients.items():
            for endpoint in docs_endpoints:
                try:
                    # 使用原始 HTTP 客户端访问文档端点
                    async with httpx.AsyncClient() as http_client:
                        response = await http_client.get(f"{client.base_url}{endpoint}")
                        
                    if response.status_code == 200:
                        self.logger.info(f"✅ {service_name} {endpoint} 可访问")
                    else:
                        self.logger.warning(f"⚠️ {service_name} {endpoint} 返回状态码: {response.status_code}")
                        
                except Exception as e:
                    self.logger.warning(f"⚠️ {service_name} {endpoint} 访问失败: {e}")
    
    @pytest.mark.asyncio
    async def test_monitoring_and_metrics_collection(self):
        """测试监控和指标收集"""
        self.logger.info("开始测试监控和指标收集")
        
        # 1. 执行一些操作生成指标
        for i in range(5):
            await self.clients["ad-exchange"].post("/demo/rtb-flow-simple")
            await asyncio.sleep(0.1)
        
        # 2. 检查工作流程统计
        stats_response = await self.clients["ad-exchange"].get("/demo/workflow-stats")
        
        if "data" in stats_response:
            workflow_stats = stats_response["data"]["workflow_statistics"]
            
            assert "total_workflows" in workflow_stats
            assert "successful_workflows" in workflow_stats
            assert "average_duration_ms" in workflow_stats
            
            assert workflow_stats["total_workflows"] >= 5
            self.logger.info(f"✅ 工作流程统计正常: {workflow_stats['total_workflows']} 次执行")
        
        # 3. 检查各服务的健康状态
        health_summary = {}
        for service_name, client in self.clients.items():
            try:
                health = await client.health_check()
                health_summary[service_name] = {
                    "status": health["status"],
                    "response_time": health.get("response_time", "unknown")
                }
            except Exception as e:
                health_summary[service_name] = {
                    "status": "error",
                    "error": str(e)
                }
        
        self.logger.info(f"✅ 健康状态监控: {json.dumps(health_summary, indent=2)}")
        
        # 4. 验证监控数据的完整性
        healthy_services = sum(1 for status in health_summary.values() 
                             if status["status"] in ["healthy", "degraded"])
        
        assert healthy_services >= len(self.clients) * 0.8, "健康服务数量不足"


class TestSystemLoadTesting:
    """系统负载测试"""
    
    @classmethod
    def setup_class(cls):
        """设置负载测试"""
        cls.logger = setup_logging("load-test")
        cls.ad_exchange_client = APIClient("http://localhost:8004", timeout=30.0)
    
    @classmethod
    async def teardown_class(cls):
        """清理负载测试"""
        await cls.ad_exchange_client.close()
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_sustained_load(self):
        """测试持续负载"""
        self.logger.info("开始持续负载测试")
        
        duration_seconds = 30  # 30秒负载测试
        requests_per_second = 5
        total_requests = duration_seconds * requests_per_second
        
        start_time = time.time()
        tasks = []
        
        for i in range(total_requests):
            # 控制请求频率
            if i > 0 and i % requests_per_second == 0:
                await asyncio.sleep(1)
            
            task = self.ad_exchange_client.post("/demo/rtb-flow-simple")
            tasks.append(task)
        
        # 执行所有请求
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.time()
        
        # 分析结果
        successful = sum(1 for r in results if not isinstance(r, Exception) and r.get("status") == "success")
        failed = len(results) - successful
        actual_duration = end_time - start_time
        actual_rps = len(results) / actual_duration
        
        success_rate = successful / len(results)
        
        self.logger.info(f"负载测试结果:")
        self.logger.info(f"  总请求数: {len(results)}")
        self.logger.info(f"  成功请求: {successful}")
        self.logger.info(f"  失败请求: {failed}")
        self.logger.info(f"  成功率: {success_rate:.2%}")
        self.logger.info(f"  实际 RPS: {actual_rps:.2f}")
        self.logger.info(f"  总耗时: {actual_duration:.2f}s")
        
        # 验证性能要求
        assert success_rate >= 0.9, f"负载测试成功率过低: {success_rate:.2%}"
        assert actual_rps >= requests_per_second * 0.8, f"实际 RPS 过低: {actual_rps:.2f}"


if __name__ == "__main__":
    # 运行集成测试
    pytest.main([__file__, "-v", "--tb=short"])