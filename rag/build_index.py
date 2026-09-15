import numpy as np
import json

from sentence_transformers import SentenceTransformer


with open("data/books.json", "r", encoding="utf-8") as file:
    books = json.load(file)


documents = []

for book in books:
    text = (
        book["title"]
        + " "
        + book["author"]
        + " "
        + book["category"]
        + " "
        + book["description"]
    )

    documents.append(text)


model = SentenceTransformer(
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)


embeddings = model.encode(documents)

#.npy 就是 NumPy 用来保存数组的一种文件格式
np.save("data/book_embeddings.npy", embeddings)


print("Books:", len(books))
print("Embeddings shape:", embeddings.shape)
print("Embeddings saved!")