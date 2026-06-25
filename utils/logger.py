import logging, os, sys

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

    # Console — Windows safe encoding
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.stream = open(sys.stdout.fileno(), mode='w',
                     encoding='utf-8', errors='replace', closefd=False)
    logger.addHandler(ch)

    # File
    fh = logging.FileHandler("logs/shahkar.log", encoding='utf-8')
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger

log = get_logger()
