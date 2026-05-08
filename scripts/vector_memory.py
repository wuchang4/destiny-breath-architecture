"""
向量记忆检索系统 (Vector Memory)
- 用语义搜索替代全量读取 MEMORY.md
- 每次只注入跟当前任务相关的记忆片段
- 依赖: Ollama + nomic-embed-text (已就绪)
"""

import json, os, re, hashlib, time
from typing import Optional
import urllib.request

# ── 配置 ──
OLLAMA_URL = "http://localhost:11434/api/embed"
MODEL = "nomic-embed-text"
MEMORY_FILE = os.path.expanduser(r"E:\claw gongzuo\.workbuddy\Claw\.workbuddy\memory\MEMORY.md")
INDEX_DIR = os.path.expanduser("~/.clawdbot/vector-memory")
INDEX_FILE = os.path.join(INDEX_DIR, "index.json")
DAILY_DIR = os.path.expanduser(r"E:\claw gongzuo\.workbuddy\Claw\.workbuddy\memory")

os.makedirs(INDEX_DIR, exist_ok=True)

# ── 文本分块 ──
def chunk_markdown(text: str, source: str) -> list[dict]:
    """把 Markdown 按二级标题分块"""
    chunks = []
    current_section = "general"
    current_text = []
    
    for line in text.split("\n"):
        if line.startswith("## "):
            if current_text:
                chunks.append({
                    "id": hashlib.md5("".join(current_text).encode()).hexdigest()[:12],
                    "section": current_section,
                    "text": "\n".join(current_text).strip(),
                    "source": source,
                })
            current_section = line.strip("# ").strip()
            current_text = []
        else:
            current_text.append(line)
    
    if current_text:
        chunks.append({
            "id": hashlib.md5("".join(current_text).encode()).hexdigest()[:12],
            "section": current_section,
            "text": "\n".join(current_text).strip(),
            "source": source,
        })
    
    return [c for c in chunks if len(c["text"]) > 20]

# ── 获取嵌入向量 ──
def get_embedding(text: str) -> list[float]:
    data = json.dumps({"model": MODEL, "input": text}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=data, headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())
    return result["embeddings"][0]

def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x*y for x,y in zip(a,b))
    na = sum(x*x for x in a)**0.5
    nb = sum(y*y for y in b)**0.5
    return dot / (na * nb) if na * nb else 0

# ── 构建/更新索引 ──
def build_index():
    print("[向量记忆] 构建/更新索引...")
    
    # 读取现有索引
    index = {"chunks": [], "version": 2}
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE) as f:
                index = json.load(f)
        except:
            index = {"chunks": [], "version": 2}
    
    existing_ids = {c["id"] for c in index["chunks"]}
    
    # 扫描需要索引的文件
    files_to_index = []
    if os.path.exists(MEMORY_FILE):
        files_to_index.append(MEMORY_FILE)
    
    # 取最近7天的daily log
    if os.path.exists(DAILY_DIR):
        daily_files = sorted([f for f in os.listdir(DAILY_DIR) if f.endswith(".md") and f[0].isdigit()], reverse=True)
        for fname in daily_files[:7]:
            files_to_index.append(os.path.join(DAILY_DIR, fname))
    
    new_chunks = 0
    for fpath in files_to_index:
        with open(fpath, encoding="utf-8") as f:
            text = f.read()
        chunks = chunk_markdown(text, os.path.basename(fpath))
        for c in chunks:
            if c["id"] not in existing_ids:
                # 计算嵌入向量
                c["embedding"] = get_embedding(c["section"] + ": " + c["text"][:500])
                index["chunks"].append(c)
                existing_ids.add(c["id"])
                new_chunks += 1
                if new_chunks % 5 == 0:
                    print(f"   已索引 {new_chunks} 个新片段...")
    
    # 保存索引
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    
    print(f"   ✅ 索引完成: {len(index['chunks'])} 个片段 (新增 {new_chunks})")

# ── 语义检索 ──
def search(query: str, top_k: int = 3, threshold: float = 0.3) -> list[dict]:
    """按语义相似度搜索记忆，返回最相关的片段"""
    if not os.path.exists(INDEX_FILE):
        build_index()
    
    with open(INDEX_FILE, encoding="utf-8") as f:
        index = json.load(f)
    
    if not index["chunks"]:
        return []
    
    q_emb = get_embedding(query)
    
    scored = []
    for c in index["chunks"]:
        if "embedding" not in c:
            continue
        score = cosine_similarity(q_emb, c["embedding"])
        if score >= threshold:
            scored.append((score, c))
    
    scored.sort(key=lambda x: -x[0])
    results = scored[:top_k]
    
    return [{
        "score": round(s, 3),
        "section": c["section"],
        "source": c["source"],
        "text": c["text"][:300],
    } for s, c in results]

# ── 智能读取（替代全量读 MEMORY.md）──
def smart_read(query: str) -> str:
    """根据当前任务查询语义相关的记忆，输出压缩后的上下文"""
    results = search(query, top_k=5, threshold=0.25)
    
    if not results:
        # 兜底：返回 MEMORY.md 前 30 行
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, encoding="utf-8") as f:
                lines = f.readlines()[:30]
            return "".join(lines)
        return ""
    
    output = []
    output.append("⚡ 向量记忆检索结果 (按相关性排序):\n")
    for r in results:
        output.append(f"\n[{r['section']}] (相关度: {r['score']})")
        output.append(f"  来源: {r['source']}")
        output.append(f"  {r['text']}")
    
    return "\n".join(output)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build_index()
    elif len(sys.argv) > 2 and sys.argv[1] == "search":
        result = search(" ".join(sys.argv[2:]))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("用法:")
        print("  python vector_memory.py build          # 构建索引")
        print("  python vector_memory.py search <query>  # 搜索")
