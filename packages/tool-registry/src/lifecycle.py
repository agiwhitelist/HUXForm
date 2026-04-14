from enum import Enum

class ToolState(Enum):
    DISCOVERED = "discovered"
    REGISTERED = "registered"
    AVAILABLE = "available"
    EXECUTING = "executing"
    FAILED = "failed"
    UNREGISTERED = "unregistered"
