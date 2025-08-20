"""
Configuration management for the ad system.
Handles loading configuration from files and environment variables.
"""

import os
import json
import logging
from typing import Dict, Any, Optional, Union
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()


@dataclass
class DatabaseConfig:
    """Database configuration."""
    url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./ad_system.db"))
    sync_url: str = field(default_factory=lambda: os.getenv("SYNC_DATABASE_URL", "sqlite:///./ad_system.db"))
    echo: bool = field(default_factory=lambda: os.getenv("DATABASE_ECHO", "false").lower() == "true")
    pool_size: int = field(default_factory=lambda: int(os.getenv("DATABASE_POOL_SIZE", "5")))
    max_overflow: int = field(default_factory=lambda: int(os.getenv("DATABASE_MAX_OVERFLOW", "10")))
    pool_timeout: int = field(default_factory=lambda: int(os.getenv("DATABASE_POOL_TIMEOUT", "30")))
    pool_recycle: int = field(default_factory=lambda: int(os.getenv("DATABASE_POOL_RECYCLE", "3600")))


@dataclass
class ServiceConfig:
    """Service configuration."""
    name: str
    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default=8000)
    debug: bool = field(default_factory=lambda: os.getenv("DEBUG", "false").lower() == "true")
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    cors_origins: list = field(default_factory=lambda: os.getenv("CORS_ORIGINS", "*").split(","))
    
    def __post_init__(self):
        """Set service-specific port based on name."""
        port_mapping = {
            "ad-management": 8001,
            "dsp": 8002,
            "ssp": 8003,
            "ad-exchange": 8004,
            "dmp": 8005
        }
        
        # Use environment variable first, then mapping, then default
        env_port = os.getenv(f"{self.name.upper().replace('-', '_')}_PORT")
        if env_port:
            self.port = int(env_port)
        elif self.name in port_mapping:
            self.port = port_mapping[self.name]


@dataclass
class RTBConfig:
    """Real-time bidding configuration."""
    timeout_ms: int = field(default_factory=lambda: int(os.getenv("RTB_TIMEOUT_MS", "100")))
    dsp_timeout_ms: int = field(default_factory=lambda: int(os.getenv("DSP_TIMEOUT_MS", "50")))
    max_concurrent_auctions: int = field(default_factory=lambda: int(os.getenv("MAX_CONCURRENT_AUCTIONS", "100")))
    default_floor_price: float = field(default_factory=lambda: float(os.getenv("DEFAULT_FLOOR_PRICE", "0.01")))
    exchange_fee_rate: float = field(default_factory=lambda: float(os.getenv("EXCHANGE_FEE_RATE", "0.1")))


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    format: str = field(default_factory=lambda: os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    file_path: Optional[str] = field(default_factory=lambda: os.getenv("LOG_FILE_PATH"))
    max_file_size: int = field(default_factory=lambda: int(os.getenv("LOG_MAX_FILE_SIZE", "10485760")))  # 10MB
    backup_count: int = field(default_factory=lambda: int(os.getenv("LOG_BACKUP_COUNT", "5")))
    json_format: bool = field(default_factory=lambda: os.getenv("LOG_JSON_FORMAT", "false").lower() == "true")


@dataclass
class SecurityConfig:
    """Security configuration."""
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY", "your-secret-key-change-in-production"))
    algorithm: str = field(default_factory=lambda: os.getenv("ALGORITHM", "HS256"))
    access_token_expire_minutes: int = field(default_factory=lambda: int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")))
    api_key_header: str = field(default_factory=lambda: os.getenv("API_KEY_HEADER", "X-API-Key"))


@dataclass
class CacheConfig:
    """Cache configuration."""
    enabled: bool = field(default_factory=lambda: os.getenv("CACHE_ENABLED", "true").lower() == "true")
    ttl_seconds: int = field(default_factory=lambda: int(os.getenv("CACHE_TTL_SECONDS", "300")))
    max_size: int = field(default_factory=lambda: int(os.getenv("CACHE_MAX_SIZE", "1000")))


@dataclass
class MonitoringConfig:
    """Monitoring and metrics configuration."""
    enabled: bool = field(default_factory=lambda: os.getenv("MONITORING_ENABLED", "true").lower() == "true")
    metrics_port: int = field(default_factory=lambda: int(os.getenv("METRICS_PORT", "9090")))
    health_check_interval: int = field(default_factory=lambda: int(os.getenv("HEALTH_CHECK_INTERVAL", "30")))


@dataclass
class AppConfig:
    """Main application configuration."""
    service: ServiceConfig
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    rtb: RTBConfig = field(default_factory=RTBConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    
    # Service URLs for inter-service communication
    service_urls: Dict[str, str] = field(default_factory=lambda: {
        "ad-management": os.getenv("AD_MANAGEMENT_URL", "http://localhost:8001"),
        "dsp": os.getenv("DSP_URL", "http://localhost:8002"),
        "ssp": os.getenv("SSP_URL", "http://localhost:8003"),
        "ad-exchange": os.getenv("AD_EXCHANGE_URL", "http://localhost:8004"),
        "dmp": os.getenv("DMP_URL", "http://localhost:8005"),
    })


class ConfigManager:
    """Configuration manager for loading and managing application configuration."""
    
    def __init__(self, service_name: str, config_file: Optional[str] = None):
        self.service_name = service_name
        self.config_file = config_file
        self._config: Optional[AppConfig] = None
        self._load_config()
    
    def _load_config(self):
        """Load configuration from file and environment variables."""
        try:
            # Start with default configuration
            service_config = ServiceConfig(name=self.service_name)
            self._config = AppConfig(service=service_config)
            
            # Load from config file if specified
            if self.config_file and Path(self.config_file).exists():
                self._load_from_file(self.config_file)
            
            # Override with environment variables (already handled in dataclass defaults)
            logger.info(f"Configuration loaded for service: {self.service_name}")
            
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            # Use default configuration as fallback
            service_config = ServiceConfig(name=self.service_name)
            self._config = AppConfig(service=service_config)
    
    def _load_from_file(self, config_file: str):
        """Load configuration from JSON file."""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # Update configuration with file data
            self._update_config_from_dict(config_data)
            logger.info(f"Configuration loaded from file: {config_file}")
            
        except Exception as e:
            logger.warning(f"Failed to load config file {config_file}: {e}")
    
    def _update_config_from_dict(self, config_data: Dict[str, Any]):
        """Update configuration from dictionary."""
        if not self._config:
            return
        
        # Update service configuration
        if "service" in config_data:
            service_data = config_data["service"]
            for key, value in service_data.items():
                if hasattr(self._config.service, key):
                    setattr(self._config.service, key, value)
        
        # Update database configuration
        if "database" in config_data:
            db_data = config_data["database"]
            for key, value in db_data.items():
                if hasattr(self._config.database, key):
                    setattr(self._config.database, key, value)
        
        # Update RTB configuration
        if "rtb" in config_data:
            rtb_data = config_data["rtb"]
            for key, value in rtb_data.items():
                if hasattr(self._config.rtb, key):
                    setattr(self._config.rtb, key, value)
        
        # Update service URLs
        if "service_urls" in config_data:
            self._config.service_urls.update(config_data["service_urls"])
    
    @property
    def config(self) -> AppConfig:
        """Get the current configuration."""
        if not self._config:
            self._load_config()
        return self._config
    
    def get_service_url(self, service_name: str) -> str:
        """Get URL for a specific service."""
        return self.config.service_urls.get(service_name, f"http://localhost:8000")
    
    def reload(self):
        """Reload configuration."""
        self._load_config()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        if not self._config:
            return {}
        
        return {
            "service": {
                "name": self._config.service.name,
                "host": self._config.service.host,
                "port": self._config.service.port,
                "debug": self._config.service.debug,
                "log_level": self._config.service.log_level,
                "cors_origins": self._config.service.cors_origins,
            },
            "database": {
                "url": self._config.database.url,
                "sync_url": self._config.database.sync_url,
                "echo": self._config.database.echo,
                "pool_size": self._config.database.pool_size,
                "max_overflow": self._config.database.max_overflow,
                "pool_timeout": self._config.database.pool_timeout,
                "pool_recycle": self._config.database.pool_recycle,
            },
            "rtb": {
                "timeout_ms": self._config.rtb.timeout_ms,
                "dsp_timeout_ms": self._config.rtb.dsp_timeout_ms,
                "max_concurrent_auctions": self._config.rtb.max_concurrent_auctions,
                "default_floor_price": self._config.rtb.default_floor_price,
                "exchange_fee_rate": self._config.rtb.exchange_fee_rate,
            },
            "service_urls": self._config.service_urls,
        }


# Global configuration instances
_config_managers: Dict[str, ConfigManager] = {}


def get_config(service_name: str, config_file: Optional[str] = None) -> AppConfig:
    """Get configuration for a service."""
    if service_name not in _config_managers:
        _config_managers[service_name] = ConfigManager(service_name, config_file)
    return _config_managers[service_name].config


def get_config_manager(service_name: str, config_file: Optional[str] = None) -> ConfigManager:
    """Get configuration manager for a service."""
    if service_name not in _config_managers:
        _config_managers[service_name] = ConfigManager(service_name, config_file)
    return _config_managers[service_name]


def create_default_config_file(service_name: str, output_path: str = "config.json"):
    """Create a default configuration file."""
    config_manager = ConfigManager(service_name)
    config_dict = config_manager.to_dict()
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(config_dict, f, indent=2, ensure_ascii=False)
        logger.info(f"Default configuration file created: {output_path}")
    except Exception as e:
        logger.error(f"Failed to create config file: {e}")
        raise


# Environment-specific configuration helpers
def is_development() -> bool:
    """Check if running in development environment."""
    return os.getenv("ENVIRONMENT", "development").lower() == "development"


def is_production() -> bool:
    """Check if running in production environment."""
    return os.getenv("ENVIRONMENT", "development").lower() == "production"


def is_testing() -> bool:
    """Check if running in testing environment."""
    return os.getenv("ENVIRONMENT", "development").lower() == "testing"


def get_environment() -> str:
    """Get current environment."""
    return os.getenv("ENVIRONMENT", "development").lower()