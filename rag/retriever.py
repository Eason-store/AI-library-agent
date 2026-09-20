from lms.models import book_rows

import chromadb
from sentence_transformers import SentenceTransformer
#把 BM25 改成中文分词版，jieba
import jieba
#BM25
# import json
from rank_bm25 import BM25Okapi




# def load_books():
#     with open("data/books.json", "r", encoding="utf-8") as file:
#         return json.load(file)
def load_books():
    #书从数据库来（文档 3.1 的 books 表）；返回结构仍保持 list[dict]，下面四个函数一行都不用改
    return book_rows()


# 稀疏部分（BM25）：只对标题、作者做词袋检索（文档 3.3）
def build_documents(books):
    documents = []

    for book in books:
        text = (
            book["title"]
            + " "
            + book["author"]
        )

        documents.append(text)

    return documents



#专门负责分词的函数    
def tokenize(text):
    return list(jieba.cut(text.lower()))



#BM25（Best Matching 25 用于信息检索和搜索引擎的经典相关性评分与排序算法）关键词强，语义弱
def bm25_search(query, top_k=3):
    books = load_books()
    documents = build_documents(books)

    tokenized_documents = [
        #document.lower().split()
        tokenize(document)
        for document in documents
    ]

    bm25 = BM25Okapi(tokenized_documents)

    #tokenized_query = query.lower().split()
    tokenized_query = tokenize(query)

    scores = bm25.get_scores(tokenized_query)

    ranked_indices = sorted(
        range(len(scores)),
        key=lambda i: scores[i],
        reverse=True
    )

    results = []

    # for index in ranked_indices[:top_k]:
    #     results.append({
    #         "book": books[index],
    #         "score": float(scores[index])
    #     })

#修复 Hybrid 的候选结果，我们不应该让 BM25 score = 0 的书进入 RRF。
    for index in ranked_indices:
        if scores[index] <= 0:
            continue

        results.append({
            "book": books[index],
            "score": float(scores[index])
        })

        if len(results) >= top_k:
            break

    return results



#在 retriever.py 加载向量模型, 必须和 build_index.py 使用同一个模型。
model = SentenceTransformer(
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)



#向量查询：改成查 Chroma，语义强，精准关键词可能弱（文档 3.3）
def vector_search(query, top_k=3):
    books = load_books()

    book_map = {
        book["book_id"]: book
        for book in books
    }

    # 1. 连接 build_index 建好的 Chroma 数据库
    client = chromadb.PersistentClient(
        path="data/chroma_db"
    )

    # 2. 拿到 books collection
    collection = client.get_collection(
        name="books"
    )

    # 3. 把用户 Query 也变成向量，必须和 build_index.py 用同一个模型
    query_embedding = model.encode(
        [query],
        normalize_embeddings=True
    )[0]

    # 4. 在 Chroma 里查最相似的书
    chroma_results = collection.query(
        query_embeddings=[query_embedding.tolist()],
        n_results=top_k
    )

    results = []

    # 5. Chroma 给的是 cosine 距离（1 - 相似度），换算回相似度当分数
    for book_id, distance in zip(
        chroma_results["ids"][0],
        chroma_results["distances"][0]
    ):
        results.append({
            "book": book_map[book_id],
            "score": 1 - float(distance)
        })

    return results



#混合检索：用 RRF（Reciprocal Rank Fusion）融合两路排名（文档 3.3）
def hybrid_search(query, top_k=3):
    #两路各取更多候选，让融合有排名信息可用
    candidate_k = 5

    bm25_results = bm25_search(query, top_k=candidate_k)
    vector_results = vector_search(query, top_k=candidate_k)

    #RRF 只看排名不看原始分数，所以不用处理 BM25 与余弦相似度量纲不同的问题
    #k = 60 是 RRF 的标准平滑参数
    k = 60

    rrf_scores = {}

    #给 BM25 排名打 RRF 分
    for rank, item in enumerate(bm25_results, start=1):
        book_id = item["book"]["book_id"]

        if book_id not in rrf_scores:
            rrf_scores[book_id] = 0

        rrf_scores[book_id] += 1 / (k + rank)

    #给向量搜索排名打 RRF 分
    for rank, item in enumerate(vector_results, start=1):
        book_id = item["book"]["book_id"]

        if book_id not in rrf_scores:
            rrf_scores[book_id] = 0

        rrf_scores[book_id] += 1 / (k + rank)

    #按融合分重新排序
    ranked_book_ids = sorted(
        rrf_scores,
        key=rrf_scores.get,
        reverse=True
    )

    #把 book_id 找回完整书籍信息
    books = load_books()

    book_map = {
        book["book_id"]: book
        for book in books
    }

    results = []

    for book_id in ranked_book_ids[:top_k]:
        results.append({
            "book": book_map[book_id],
            #注意：这是 RRF 融合分（量级约 0.016~0.033），不是相似度
            "score": rrf_scores[book_id]
        })

    return results




# if __name__ == "__main__":
#     #results = bm25_search("人工智能", top_k=3)

#     # results = vector_search(
#     #     "我想学习机器学习和神经网络",
#     #     top_k=3
#     # )
#     results = hybrid_search(
#     "我想学习机器学习和神经网络",
#     top_k=3
#     )

#     for item in results:
#         print(
#             item["book"]["title"],
#             "-",
#             item["score"]
#         )

if __name__ == "__main__":

    query = "我想找一本教我写程序的入门书"
    top_k = 3

    print("=" * 50)
    print("Query:", query)
    print("=" * 50)

    # 1. BM25 Search
    print("\n[BM25 Search]")

    bm25_results = bm25_search(query, top_k=top_k)

    for rank, item in enumerate(bm25_results, start=1):
        print(
            rank,
            item["book"]["title"],
            "- score:",
            item["score"]
        )

    # 2. Vector Search
    print("\n[Vector Search]")

    vector_results = vector_search(query, top_k=top_k)

    for rank, item in enumerate(vector_results, start=1):
        print(
            rank,
            item["book"]["title"],
            "- score:",
            item["score"]
        )

    # 3. Hybrid Search
    print("\n[Hybrid Search]")

    hybrid_results = hybrid_search(query, top_k=top_k)

    for rank, item in enumerate(hybrid_results, start=1):
        print(
            rank,
            item["book"]["title"],
            "- RRF score:",
            item["score"]
        )

