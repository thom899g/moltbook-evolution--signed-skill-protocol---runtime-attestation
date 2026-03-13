"""
Unified logging system for MOLTBOOK Evolution with structured JSON logging
and real-time Firestore integration for audit trails.
"""

import logging
import json
import sys
import traceback
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum

# Import only after verifying Firebase is configured
try:
    from firebase_admin import firestore
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    logging.warning("Firebase Admin SDK not available. Logging to Firestore disabled.")

class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

@dataclass
class LogEntry:
    timestamp: str
    component: str
    level: str
    message: str
    skill_id: Optional[str] = None
    developer_id: Optional[str] = None
    hardware_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    stack_trace: Optional[str] = None

class MoltbookLogger:
    """Centralized logging with Firestore integration and structured output"""
    
    def __init__(self, component_name: str, firestore_client=None):
        self.component = component_name
        self.firestore_client = firestore_client
        self.console_logger = self._setup_console_logger()
        
        # Initialize critical state variables
        self.last_error = None
        self.error_count = 0
        self.telegram_alert_threshold = 3
        
    def _setup_console_logger(self) -> logging.Logger:
        """Configure structured console logging"""
        logger = logging.getLogger(f"moltbook.{self.component}")
        logger.setLevel(logging.DEBUG)
        
        # Clear existing handlers
        if logger.handlers:
            logger.handlers.clear()
        
        # JSON formatter for structured logs
        class JSONFormatter(logging.Formatter):
            def format(self, record):
                log_data = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "component": self.component,
                    "level": record.levelname,
                    "message": record.getMessage(),
                    "file": record.pathname,
                    "line": record.lineno
                }
                
                # Add extra fields if present
                if hasattr(record, 'skill_id'):
                    log_data['skill_id'] = record.skill_id
                if hasattr(record, 'developer_id'):
                    log_data['developer_id'] = record.developer_id
                if hasattr(record, 'metadata'):
                    log_data['metadata'] = record.metadata
                
                return json.dumps(log_data, ensure_ascii=False)
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(JSONFormatter())
        logger.addHandler(console_handler)
        
        # Prevent propagation to root logger
        logger.propagate = False
        
        return logger
    
    def _create_log_entry(self, level: LogLevel, message: str, **kwargs) -> LogEntry:
        """Create a structured log entry with error handling"""
        try:
            metadata = kwargs.get('metadata', {})
            skill_id = kwargs.get('skill_id')
            developer_id = kwargs.get('developer_id')
            hardware_id = kwargs.get('hardware_id')
            stack_trace = kwargs.get('stack_trace')
            
            if level == LogLevel.ERROR or level == LogLevel.CRITICAL:
                if not stack_trace:
                    stack_trace = ''.join(traceback.format_stack())
                self.error_count += 1
                self.last_error = message
            
            return LogEntry(
                timestamp=datetime.utcnow().isoformat(),
                component=self.component,
                level=level.value,
                message=message,
                skill_id=skill_id,
                developer_id=developer_id,
                hardware_id=hardware_id,
                metadata=metadata,
                stack_trace=stack_trace
            )
        except Exception as e:
            # Fallback if log creation fails
            return LogEntry(
                timestamp=datetime.utcnow().isoformat(),
                component=self.component,
                level=LogLevel.ERROR.value,
                message=f"Failed to create log entry: {str(e)}",
                metadata={"original_message": message}
            )
    
    def _log_to_firestore(self, entry: LogEntry) -> bool:
        """Asynchronously log to Firestore with error handling"""
        if not FIREBASE_AVAILABLE or not self.firestore_client:
            return False
        
        try:
            # Use timestamp as document ID for uniqueness
            doc_id = entry.timestamp.replace(':', '-').replace('.', '-')
            doc_ref = self.firestore_client.collection('system_logs').document(doc_id)
            doc_ref.set(asdict(entry))
            return True
        except Exception as e:
            # Log Firestore failure to console but don't crash
            self.console_logger.error(f"Failed to log to Firestore: {str(e)}")
            return False
    
    def debug(self, message: str, **kwargs):
        """Log debug message"""
        entry = self._create_log_entry(LogLevel.DEBUG, message, **kwargs)
        self.console_logger.debug(message, extra=kwargs)
        self._log_to_firestore(entry)
    
    def info(self, message: str, **kwargs):
        """Log info message"""
        entry = self._create_log_entry(LogLevel.INFO, message, **kwargs)
        self.console_logger.info(message, extra=kwargs)
        self._log_to_firestore(entry)
    
    def warning(self, message: str, **kwargs):
        """Log warning message"""
        entry = self._create_log_entry(LogLevel.WARNING, message, **kwargs)
        self.console_logger.warning(message, extra=kwargs)
        self._log_to_firestore(entry)
    
    def error(self, message: str, **kwargs):
        """Log error message with automatic stack trace"""
        if not kwargs.get('stack_trace'):
            kwargs['stack_trace'] = ''.join(traceback.format_stack())
        
        entry = self._create_log_entry(LogLevel.ERROR, message, **kwargs)
        self.console_logger.error(message, extra=kwargs)
        self._log_to_firestore(entry)
        
        # Check if we need to trigger Telegram alert
        if self.error_count >= self.telegram_alert_threshold:
            self._trigger_telegram_alert()
    
    def critical(self, message: str, **kwargs):
        """Log critical message - always triggers Telegram alert"""
        kwargs['stack_trace'] = ''.join(traceback.format_stack())
        entry = self._create_log_entry(LogLevel.CRITICAL, message, **kwargs)
        self.console_logger.critical(message, extra=kwargs)
        self._log_to_firestore(entry)
        self._trigger_telegram_alert()
    
    def _trigger_telegram_alert(self):
        """Trigger emergency Telegram alert"""
        # This will be implemented in emergency_contact.py
        # For now, just log the intent
        self.console_logger.critical(
            "TELEGRAM ALERT TRIGGERED",
            metadata={
                "error_count": self.error_count,
                "last_error": self.last_error,
                "component": self.component
            }
        )
    
    def get_error_stats(self) -> Dict[str, Any]:
        """Return error statistics for monitoring"""
        return {
            "error_count": self.error_count,
            "last_error": self.last_error,
            "component": self.component,
            "timestamp": datetime.utcnow().isoformat()
        }

# Global logger instance for system startup
system_logger = MoltbookLogger("system_bootstrap")