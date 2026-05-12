"""
语义技能筛选器 (Semantic Skill Selector)
- 用语义搜索从130+技能中精准定位最相关的技能
- 替代关键词匹配，解决"技能太多加载不了"的问题
- 依赖: Ollama + nomic-embed-text（复用 vector_memory 基础设施）
- 参考: Strands Agents 的 Semantic Tool Scaling 模式

用法:
    python skill_index.py build           # 构建/重建技能索引
    python skill_index.py search "写文章"  # 搜索最相关的技能
    python skill_index.py search "抖音自动化" --top 3
"""

import json, os, glob, hashlib, time, sys
from typing import Optional
import urllib.request

# ── 配置 ──
OLLAMA_URL = "http://localhost:11434/api/embed"
MODEL = "nomic-embed-text"
SKILLS_DIR = os.path.expanduser(r"C:\Users\admin\.workbuddy\skills")
INDEX_DIR = os.path.expanduser(r"~/.clawdbot/vector-memory")
SKILL_INDEX_FILE = os.path.join(INDEX_DIR, "skill_index.json")

os.makedirs(INDEX_DIR, exist_ok=True)


def get_embedding(text: str) -> list[float]:
    data = json.dumps({"model": MODEL, "input": text}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=data, headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read())
    return result["embeddings"][0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na * nb else 0


def extract_skill_meta(skill_dir: str) -> dict:
    """从技能目录提取元数据"""
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(skill_md):
        return None

    with open(skill_md, encoding="utf-8", errors="ignore") as f:
        content = f.read()

    meta = {
        "name": os.path.basename(skill_dir),
        "path": skill_dir,
        "description": "",
        "keywords": [],
        "triggers": [],
        "hub": "",
    }

    # 解析 frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            for line in frontmatter.strip().split("\n"):
                line = line.strip()
                if line.startswith("description:"):
                    meta["description"] = line.split(":", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("name:"):
                    meta["name"] = line.split(":", 1)[1].strip().strip('"').strip("'")

    # 从目录名推断 Hub 归属
    parts = skill_dir.replace(SKILLS_DIR, "").strip(os.sep).split(os.sep)
    if len(parts) > 1:
        meta["hub"] = parts[0]

    # 从内容提取触发词（常见模式）
    trigger_patterns = [
        "触发词：", "触发词:", "Use when:", "Triggers on:",
        "触发场景：", "触发场景:", "trigger:", "Trigger:"
    ]
    for pattern in trigger_patterns:
        if pattern in content:
            idx = content.index(pattern)
            snippet = content[idx:idx + 500].split("\n")[0]
            meta["triggers"].append(snippet.strip())

    # 提取关键词（从文件名和描述中）
    text = f"{meta['name']} {meta['description']} {' '.join(meta['triggers'])}"
    # 清理特殊字符
    text = text.replace("_", " ").replace("-", " ").replace("/", " ")
    meta["keywords"] = list(set(text.lower().split()))[:30]

    return meta


def build_skill_index():
    """构建全部技能的向量索引"""
    print("[skill-index] 扫描技能目录...")
    skill_dirs = []
    for root, dirs, files in os.walk(SKILLS_DIR):
        if "SKILL.md" in files:
            skill_dirs.append(root)

    print(f"[skill-index] 找到 {len(skill_dirs)} 个技能")

    index = {"skills": [], "version": 1, "built_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    existing = {}
    if os.path.exists(SKILL_INDEX_FILE):
        try:
            with open(SKILL_INDEX_FILE) as f:
                old = json.load(f)
                existing = {s["name"]: s for s in old.get("skills", [])}
        except:
            pass

    built = 0
    skipped = 0
    for skill_dir in sorted(skill_dirs):
        meta = extract_skill_meta(skill_dir)
        if not meta:
            continue

        # 生成嵌入文本：name + description + triggers
        embed_text = f"{meta['name']}: {meta['description']}. {' '.join(meta['triggers'])}"

        # 跳过未变化的（基于内容哈希）
        content_hash = hashlib.md5(embed_text.encode()).hexdigest()[:12]
        if meta["name"] in existing and existing[meta["name"]].get("hash") == content_hash:
            index["skills"].append(existing[meta["name"]])
            skipped += 1
            continue

        try:
            embedding = get_embedding(embed_text)
            skill_entry = {
                **meta,
                "embedding": embedding,
                "hash": content_hash,
                "embed_text": embed_text[:200],
            }
            index["skills"].append(skill_entry)
            built += 1
            if built % 10 == 0:
                print(f"  [{built}/{len(skill_dirs)}] 已索引...")
        except Exception as e:
            print(f"  ⚠ 嵌入失败: {meta['name']}: {e}")

    # 保存索引
    with open(SKILL_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"[skill-index] 完成: 新建 {built}, 跳过 {skipped}, 总计 {len(index['skills'])} 个技能已索引")
    print(f"[skill-index] 索引文件: {SKILL_INDEX_FILE}")
    return index


def search_skills(query: str, top_k: int = 5, threshold: float = 0.25) -> list[dict]:
    """语义搜索最相关的技能"""
    if not os.path.exists(SKILL_INDEX_FILE):
        print("[skill-index] 索引不存在，先运行: python skill_index.py build")
        return []

    with open(SKILL_INDEX_FILE, encoding="utf-8") as f:
        index = json.load(f)

    skills = index.get("skills", [])
    if not skills:
        return []

    # 获取查询的嵌入向量
    query_embedding = get_embedding(query)

    # 计算余弦相似度
    results = []
    for skill in skills:
        if not skill.get("embedding"):
            continue
        score = cosine_similarity(query_embedding, skill["embedding"])
        if score >= threshold:
            results.append({
                "name": skill["name"],
                "hub": skill.get("hub", ""),
                "description": skill.get("description", "")[:150],
                "score": round(score, 4),
                "path": skill.get("path", ""),
            })

    # 按分数降序排列
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def print_results(results: list[dict], query: str):
    """格式化输出搜索结果"""
    if not results:
        print(f"未找到与 '{query}' 相关的技能（阈值可能太高）")
        return

    print(f"\n🔍 语义搜索: \"{query}\"")
    print(f"   找到 {len(results)} 个最相关技能:\n")
    for i, r in enumerate(results, 1):
        score_bar = "█" * int(r["score"] * 20)
        print(f"  {i}. [{r['score']:.3f}] {score_bar}")
        print(f"     📦 {r['name']}")
        if r["hub"]:
            print(f"     🏠 Hub: {r['hub']}")
        if r["description"]:
            print(f"     📝 {r['description']}")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法:")
        print("  python skill_index.py build              # 构建技能索引")
        print("  python skill_index.py search '查询内容'   # 搜索技能")
        print("  python skill_index.py search '查询' --top 3")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "build":
        build_skill_index()
    elif cmd == "search":
        if len(sys.argv) < 3:
            print("用法: python skill_index.py search '查询内容'")
            sys.exit(1)
        query = sys.argv[2]
        top_k = 5
        if "--top" in sys.argv:
            idx = sys.argv.index("--top")
            if idx + 1 < len(sys.argv):
                top_k = int(sys.argv[idx + 1])
        results = search_skills(query, top_k=top_k)
        print_results(results, query)
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)
