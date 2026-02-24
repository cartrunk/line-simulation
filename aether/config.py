# LM Studio endpoint — change LLM_MODEL to match whatever is loaded in LM Studio
LM_STUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
LM_STUDIO_API_KEY  = "lm-studio"   # not validated locally, just satisfies the client
LLM_MODEL          = "local-model"  # replace with your model's identifier

# Soul
SOUL_CYCLE_SECONDS      = 300   # how often the background motivation loop fires
GOAL_PRIORITY_THRESHOLD = 0.65  # minimum priority for a Soul-generated goal to be accepted

# Memory
SURPRISE_THRESHOLD  = 0.4   # novelty score above which memory is written
RECALL_TOP_K        = 20    # episodes retrieved per Soul cycle
MEMORY_PERSIST_DIR  = "./aether_memory"   # chromadb on-disk path

# Agency
MAX_ACTION_HISTORY = 50
