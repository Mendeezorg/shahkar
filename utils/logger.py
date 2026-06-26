import logging, os, sys
from collections import deque

# In-memory log buffer for dashboard
_log_buffer = deque(maxlen=100)

class BufferHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        _log_buffer.append(msg)

def get_log_buffer():
    return list(_log_buffer)

def get_logger(name="SHAHKAR"):
    os.makedirs("logs", exist_ok=True)
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    try:
        ch.stream = open(sys.stdout.fileno(), mode='w',
                         encoding='utf-8', errors='replace', closefd=False)
    except Exception:
        pass
    logger.addHandler(ch)

    # File
    try:
        fh = logging.FileHandler("logs/shahkar.log", encoding='utf-8')
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass

    # Memory buffer for dashboard
    bh = BufferHandler()
    bh.setFormatter(fmt)
    logger.addHandler(bh)

    return logger

log = get_logger()
