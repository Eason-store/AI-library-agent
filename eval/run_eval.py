import json

from rag.retriever import (
    bm25_search,
    vector_search,
    hybrid_search
)

# 把cases.jsonl一行一行读进来。
def load_cases():
    cases = []

    with open("eval/cases.jsonl", "r", encoding="utf-8") as file:
        for line in file:
            #如果遇到空白行，直接跳过去，不要拿空白行执行 json.loads()
            line = line.strip()
            if not line:
                continue

            # cases.append(json.loads(line))
            case = json.loads(line)

            #只跑检索类用例（type = retrieval）；以后补的端到端用例（type = e2e）不走这条评测
            if case.get("type", "retrieval") != "retrieval":
                continue

            cases.append(case)            

    return cases




# 找到的相关书数量
# ÷
# 所有应该找到的相关书数量
# relevant_ids = ["B006", "B005"]
# retrieved_ids = ["B006", "B004", "B003"]
# 交集只有：B006，1 / 2 = 0.5，Recall@3 = 0.50
def recall_at_k(results, relevant_ids):
    retrieved_ids = [
        item["book"]["book_id"]
        for item in results
    ]

    relevant_set = set(relevant_ids)
    retrieved_set = set(retrieved_ids)

    hits = len(relevant_set & retrieved_set)

    return hits / len(relevant_set)

#evaluate() 则会对每个 query 都跑一次检索，再算 Recall，最后取平均值。
def evaluate(search_function, cases, top_k=3):
    recalls = []

    for case in cases:
        query = case["query"]
        relevant_ids = case["relevant_ids"]

        results = search_function(
            query,
            top_k=top_k
        )

        recall = recall_at_k(
            results,
            relevant_ids
        )

        recalls.append(recall)

        print("Query:", query)
        print("Relevant:", relevant_ids)
        print(
            "Retrieved:",
            [item["book"]["book_id"] for item in results]
        )
        print(f"Recall@{top_k}: {recall:.2f}")
        print("-" * 50)

    average_recall = sum(recalls) / len(recalls)

    return average_recall


if __name__ == "__main__":
    cases = load_cases()
    top_k = 5

    print("\n===== BM25 =====")
    bm25_recall = evaluate(
        bm25_search,
        cases,
        top_k=top_k
    )

    print("\n===== VECTOR =====")
    vector_recall = evaluate(
        vector_search,
        cases,
        top_k=top_k
    )

    print("\n===== HYBRID =====")
    hybrid_recall = evaluate(
        hybrid_search,
        cases,
        top_k=top_k
    )

    print("\n===== SUMMARY =====")
    print(f"BM25 Recall@{top_k}:   {bm25_recall:.2f}")
    print(f"Vector Recall@{top_k}: {vector_recall:.2f}")
    print(f"Hybrid Recall@{top_k}: {hybrid_recall:.2f}")