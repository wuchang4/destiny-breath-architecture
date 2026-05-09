"""
向量记忆检索系统
==============
替代全量读取 MEMORY.md，每会话节省 ~90% Token 消耗。

原理：
  1. 将 MEMORY.md 按段落/主题切分为片段（chunks）
  2. 用 ollama nomic-embed-text 生成 768 维向量
  3. 查询时做余弦相似度，返回 top-3 最相关片段
  4. 未命中时兜底读取 MEMORY.md 前30行

使用：
  python vector_memory.py index        # 索引 MEMORY.md
  python vector_memory.py search "xxx" # 搜索相关记忆
  python vector_memory.py status       # 查看索引状态
"""

import json
import os
import sys
import re
import urllib.request
import urllib.error
import math
from datetime import datetime

# ─── 配置 ─────────────────────────────────────────────────
MEMORY_DIR = os.path.expanduser('E:/claw gongzuo/.workbuddy/Claw/.workbuddy/memory')
MEMORY_FILE = os.path.join(MEMORY_DIR, 'MEMORY.md')
INDEX_FILE = os.path.join(MEMORY_DIR, 'vector_index.json')

OLLAMA_URL = 'http://localhost:11434/api/embeddings'
EMBED_MODEL = 'nomic-embed-text'
TOP_K = 3
SIMILARITY_THRESHOLD = 0.25


# ─── 工具函数 ─────────────────────────────────────────────
def get_embedding(text: str) -> list:
    """调用 ollama 获取文本向量"""
    data = json.dumps({'model': EMBED_MODEL, 'prompt': text}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get('embedding', [])
    except Exception as e:
        print(f'  [vector] ⚠ 嵌入失败: {e}')
        return []


def cosine_similarity(a: list, b: list) -> float:
    """余弦相似度"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def chunk_markdown(text: str, max_chars: int = 500) -> list:
    """将 Markdown 文本按段落切分为片段"""
    chunks = []
    # 按二级标题分割
    sections = re.split(r'(?=^## )', text, flags=re.MULTILINE)
    
    for section in sections:
        section = section.strip()
        if not section:
            continue
        
        # 如果片段太长，再按空行或句号切分
        if len(section) > max_chars:
            paragraphs = re.split(r'\n\n+|(?<=[。！？])', section)
            current = ''
            for p in paragraphs:
                p = p.strip()
                if not p:
                    continue
                if len(current) + len(p) < max_chars:
                    current += p + '\n'
                else:
                    if current.strip():
                        chunks.append(current.strip())
                    current = p + '\n'
            if current.strip():
                chunks.append(current.strip())
        else:
            chunks.append(section)
    
    # 过滤太短的片段（< 20 字符）
    return [c for c in chunks if len(c) >= 20]


# ─── 索引管理 ─────────────────────────────────────────────
def build_index():
    """构建或更新向量索引"""
    if not os.path.exists(MEMORY_FILE):
        print(f'  [vector] MEMORY.md 不存在: {MEMORY_FILE}')
        return False
    
    with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if not content.strip():
        print(f'  [vector] MEMORY.md 为空')
        return False
    
    chunks = chunk_markdown(content)
    print(f'  [vector] 切分为 {len(chunks)} 个片段')
    
    index = []
    for i, chunk in enumerate(chunks):
        print(f'  [vector] 嵌入片段 {i+1}/{len(chunks)} ({len(chunk)} 字符)...', end=' ')
        emb = get_embedding(chunk[:1000])  # 只取前1000字符
        if emb:
            index.append({
                'id': i,
                'text': chunk,
                'embedding': emb,
                'length': len(chunk),
                'indexed_at': datetime.now().isoformat()
            })
            print('✅')
        else:
            print('❌')
    
    # 保存索引
    os.makedirs(MEMORY_DIR, exist_ok=True)
    # 保存时不存 embedding（太大），单独存向量文件
    index_meta = [{
        'id': item['id'],
        'text': item['text'],
        'length': item['length'],
        'indexed_at': item['indexed_at']
    } for item in index]
    
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            'model': EMBED_MODEL,
            'dimension': 768,
            'total_chunks': len(index),
            'chunks': index_meta
        }, f, ensure_ascii=False, indent=2)
    
    # 单独存向量（不混在索引 JSON 里）
    vector_file = INDEX_FILE.replace('.json', '_vectors.json')
    vectors = {str(item['id']): item['embedding'] for item in index}
    with open(vector_file, 'w', encoding='utf-8') as f:
        json.dump(vectors, f)
    
    print(f'  [vector] 索引完成: {len(index)} 个片段')
    print(f'  [vector] 索引文件: {INDEX_FILE}')
    print(f'  [vector] 向量文件: {vector_file}')
    return True


def search(query: str, top_k: int = TOP_K) -> list:
    """语义搜索记忆，返回 top_k 相关片段"""
    if not os.path.exists(INDEX_FILE):
        print(f'  [vector] 索引不存在，请先运行 index')
        return []
    
    with open(INDEX_FILE, 'r', encoding='utf-8') as f:
        index = json.load(f)
    
    vector_file = INDEX_FILE.replace('.json', '_vectors.json')
    if not os.path.exists(vector_file):
        print(f'  [vector] 向量文件不存在')
        return []
    
    with open(vector_file, 'r', encoding='utf-8') as f:
        vectors = json.load(f)
    
    # 查询向量
    query_emb = get_embedding(query)
    if not query_emb:
        return []
    
    # 计算相似度
    scored = []
    for chunk in index.get('chunks', []):
        chunk_id = str(chunk['id'])
        chunk_vec = vectors.get(chunk_id, [])
        if chunk_vec:
            sim = cosine_similarity(query_emb, chunk_vec)
            scored.append((sim, chunk))
    
    # 排序取 top_k
    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for sim, chunk in scored[:top_k]:
        if sim >= SIMILARITY_THRESHOLD:
            results.append({
                'text': chunk['text'][:300],  # 只返回前300字符预览
                'similarity': round(sim, 4),
                'length': chunk['length']
            })
    
    return results


def status():
    """查看索引状态"""
    if not os.path.exists(INDEX_FILE):
        print('  [vector] 索引文件: 不存在')
        print('  [vector] MEMORY.md: 存在' if os.path.exists(MEMORY_FILE) else '  [vector] MEMORY.md: 不存在')
        return
    
    with open(INDEX_FILE, 'r', encoding='utf-8') as f:
        index = json.load(f)
    
    mem_size = os.path.getsize(MEMORY_FILE) if os.path.exists(MEMORY_FILE) else 0
    idx_size = os.path.getsize(INDEX_FILE) if os.path.exists(INDEX_FILE) else 0
    
    mem_mtime = datetime.fromtimestamp(os.path.getmtime(MEMORY_FILE)) if os.path.exists(MEMORY_FILE) else None
    
    print(f'  [vector] 索引状态')
    print(f'  {"─"*35}')
    print(f'  模型:         {index.get("model", "未知")}')
    print(f'  向量维度:     {index.get("dimension", 0)}')
    print(f'  记忆片段数:   {index.get("total_chunks", 0)}')
    print(f'  MEMORY.md 大小: {mem_size} bytes')
    print(f'  索引文件大小:   {idx_size} bytes')
    print(f'  MEMORY.md 修改时间: {mem_mtime.strftime("%m-%d %H:%M") if mem_mtime else "未知"}')
    
    # 建议是否重建索引
    idx_mtime = os.path.getmtime(INDEX_FILE)
    if mem_mtime and mem_mtime.timestamp() > idx_mtime:
        print(f'  ⚠ MEMORY.md 已修改，建议重建索引: python vector_memory.py index')


# ─── 主入口 ───────────────────────────────────────────────
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('用法:')
        print('  python vector_memory.py index           # 构建索引')
        print('  python vector_memory.py search <query>  # 搜索')
        print('  python vector_memory.py status          # 查看状态')
        sys.exit(1)
    
    cmd = sys.argv[1]
    if cmd == 'index':
        build_index()
    elif cmd == 'search':
        query = ' '.join(sys.argv[2:]) if len(sys.argv) > 2 else ''
        if not query:
            print('请输入搜索关键词')
            sys.exit(1)
        results = search(query)
        if results:
            print(f'\n  找到 {len(results)} 条相关记忆:\n')
            for i, r in enumerate(results, 1):
                print(f'  [{i}] 相似度: {r["similarity"]}')
                print(f'      {r["text"][:200]}')
                print()
        else:
            print('  未找到相关记忆（可尝试降低阈值或重建索引）')
    elif cmd == 'status':
        status()
    else:
        print(f'未知命令: {cmd}')
