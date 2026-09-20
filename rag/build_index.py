# import json

# import chromadb
# from sentence_transformers import SentenceTransformer


# with open("data/books.json", "r", encoding="utf-8") as file:
#     books = json.load(file)


import chromadb
from sentence_transformers import SentenceTransformer

from lms.models import book_rows

#书从数据库来（seed 灌进去的 500 本）
books = book_rows()



# 向量部分：书名 + 作者 + 简介（文档 3.3）
documents = []

for book in books:
    text = (
        book["title"]
        + " "
        + book["author"]
        + " "
        + book["description"]
    )

    documents.append(text)


model = SentenceTransformer(
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)


embeddings = model.encode(
    documents,
    normalize_embeddings=True
)


# 文档 3.3：向量部分存 Chroma
client = chromadb.PersistentClient(path="data/chroma_db")

# 重建索引：先删掉旧 collection，避免脏数据，也避免 hnsw:space 改不动
try:
    client.delete_collection(name="books")
except Exception:
    pass

collection = client.get_or_create_collection(
    name="books",
    metadata={"hnsw:space": "cosine"}
)


collection.add(
    ids=[book["book_id"] for book in books],
    embeddings=embeddings.tolist(),
    documents=documents,
    metadatas=[
        {
            "title": book["title"],
            "author": book["author"],
            "category": book["category"],
            "call_number": book["call_number"]
        }
        for book in books
    ]
)


print("Books:", len(books))
print("Embeddings shape:", embeddings.shape)
print("Collection count:", collection.count())
print("Index saved to data/chroma_db")