r"""造测试数据：500 本书 + 50 个读者（文档第五节的 seed.py）。

重复运行会先清空 4 张表再重新灌，所以可以反复执行。
随机种子固定，每次生成的数据完全一样，方便评测复现。

运行方式（必须在项目根目录）：
    .venv\Scripts\python.exe -m lms.seed
"""
import json
import random
from datetime import datetime, timedelta

from lms import rules
from lms.models import Book, Loan, Reservation, SessionLocal, User, init_db

RANDOM_SEED = 42
BOOK_TARGET = 500
USER_TARGET = 50
ACTIVE_LOAN_COUNT = 30
OVERDUE_LOAN_COUNT = 3
RETURNED_LOAN_COUNT = 10
LEGACY_BOOKS_FILE = "data/books.json"

#类目 →（中图法分类号前缀, 主题词池）
CATEGORY_INFO = {
    "计算机": (
        "TP",
        ["Python", "Java", "C语言", "程序设计", "编程入门", "数据结构", "算法设计",
         "算法竞赛", "排序与查找", "图论", "动态规划", "操作系统", "计算机网络",
         "数据库系统", "机器学习", "深度学习", "神经网络", "自然语言处理", "计算机视觉",
         "软件工程", "编译原理", "信息安全", "云计算", "分布式系统", "嵌入式开发",
         "前端开发", "Web开发", "移动开发", "Python数据分析", "计算机组成原理"]
    ),
    "科幻": (
        "I247.5",
        ["星际", "银河", "时间", "火星", "量子", "机器人", "未来世界", "太空",
         "外星文明", "平行宇宙", "人工智能觉醒", "末日", "星际航行", "克隆", "赛博朋克",
         "时空穿梭", "太空殖民", "异星生命", "记忆移植", "虚拟现实", "深海探索",
         "太空电梯", "基因编辑", "末日废土"]
    ),
    "文学": (
        "I",
        ["故乡", "长夜", "夏日", "旧城", "远山", "雨中", "车站", "庭院",
         "老屋", "河岸", "南方", "秋日", "晨雾", "石桥", "巷口", "渡口",
         "少年", "往事", "归途", "麦田", "灯塔", "老街", "雪山", "海湾"]
    ),
    "科普": (
        "N49",
        ["宇宙", "黑洞", "量子力学", "生命演化", "地球", "数学之美", "时间", "相对论",
         "基因", "大脑", "气候", "海洋", "昆虫", "粒子物理", "进化论", "星空",
         "化学元素", "人工智能", "能源", "生态", "天文观测", "微生物", "医学简史", "气候变迁"]
    ),
    "历史": (
        "K",
        ["唐代", "宋代", "明清", "丝绸之路", "大航海", "古罗马", "近代中国", "世界史",
         "春秋战国", "秦汉", "古埃及", "中世纪", "工业革命", "冷战", "文艺复兴", "蒙古帝国",
         "两河流域", "美洲文明", "抗日战争", "城市化", "古印度", "拜占庭", "大萧条", "民族迁徙"]
    ),
    "经济": (
        "F",
        ["宏观经济学", "微观经济学", "货币金融", "投资", "管理学", "市场营销", "博弈论", "统计学",
         "国际贸易", "行为经济学", "财务报表", "供应链", "数字经济", "创业管理", "产业政策",
         "计量经济", "金融市场", "组织行为", "会计学", "保险", "金融科技", "电子商务",
         "人口经济", "城市经济"]
    ),
    "艺术": (
        "J",
        ["西方美术", "中国绘画", "电影艺术", "摄影", "建筑设计", "音乐史", "设计美学", "书法",
         "雕塑", "服饰", "陶瓷", "戏曲", "平面设计", "工业设计", "舞蹈", "版画",
         "园林", "当代艺术", "民间工艺", "电影配乐", "动画", "游戏设计", "珠宝设计", "建筑史"]
    ),
    "哲学": (
        "B",
        ["西方哲学", "中国哲学", "伦理学", "逻辑学", "美学", "认识论", "宗教", "思维",
         "形而上学", "科学哲学", "政治哲学", "心灵哲学", "语言哲学", "存在主义", "儒家思想",
         "道家思想", "佛教哲学", "现象学", "分析哲学", "应用伦理", "唯物主义", "辩证法",
         "生命伦理", "技术哲学"]
    )
}

#计算机类多给一点权重，评测用例大多落在这个类目
CATEGORY_WEIGHTS = {
    "计算机": 30,
    "文学": 15,
    "科幻": 12,
    "科普": 12,
    "历史": 10,
    "经济": 8,
    "艺术": 7,
    "哲学": 6
}

TITLE_SUFFIXES = [
    "入门与实践", "从基础到进阶", "原理与实现", "导论", "精讲",
    "实践指南", "现代方法", "案例分析", "核心技术与应用", "习题与解析",
    "简明教程", "高级教程", "工程实践", "项目实战", "关键问题",
    "研究进展", "方法与技巧", "选讲", "通识读本", "速查手册"
]
#描述用多个句式轮流生成，并把“相关主题词”写进去，避免几百本书的简介千篇一律
DESCRIPTION_TEMPLATES = [
    "本书系统介绍{topic}的基本概念、{rel1}与{rel2}，配有大量案例，适合{topic}方向的初学者与进阶读者。",
    "围绕{topic}展开，重点讲解{rel1}和{rel2}的实现思路，可作为高校课程教材或自学读物。",
    "{topic}领域的入门读物，用通俗的语言讲清{rel1}与{rel2}，每章附有练习与解析。",
    "从工程实践角度介绍{topic}，涵盖{rel1}、{rel2}等主题，适合有一定基础的读者。",
    "本书以问题驱动的方式讲解{topic}，深入分析{rel1}和{rel2}，并给出完整案例。",
    "{topic}的进阶读物，系统梳理{rel1}与{rel2}的核心内容，附有大量图示与实例。"
]



AUTHOR_FAMILY = ["李", "王", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴", "徐", "孙", "马", "朱", "胡"]
AUTHOR_GIVEN = ["伟", "芳", "娜", "敏", "静", "磊", "强", "军", "洋", "勇", "艳", "杰", "娟", "涛", "明"]
FOREIGN_AUTHORS = ["John Smith", "Emily Brown", "Michael Chen", "Sarah Lee", "David Miller", "Anna Wilson"]

#读者等级权重：普通 50 人里的比例，用来决定 max_borrow（额度仍取自 rules.py）
LEVEL_WEIGHTS = [("普通", 50), ("学生", 40), ("教师", 10)]


def make_isbn():
    #978-7-xxxxxxxx-x：前 12 位随机，最后一位按 ISBN-13 的 1/3 加权规则算校验位
    digits = "9787" + "".join(random.choice("0123456789") for _ in range(8))
    total = sum(int(ch) * (1 if i % 2 == 0 else 3) for i, ch in enumerate(digits))
    check = (10 - total % 10) % 10

    return digits + str(check)


def make_call_number(category):
    #索书号 = 分类号 + 著者号，例如 TP311.561/M42
    prefix = CATEGORY_INFO[category][0]
    letter = random.choice("ABCDEFGHJKLMNOPQRSTUVWXYZ")

    return prefix + str(random.randint(10, 999)) + "/" + letter + str(random.randint(10, 99))


def make_author():
    if random.random() < 0.25:
        return random.choice(FOREIGN_AUTHORS)

    return random.choice(AUTHOR_FAMILY) + random.choice(AUTHOR_GIVEN)


def build_legacy_books():
    """把 data/books.json 里那 15 本真书搬进数据库，保证文档第二节的样例对话能复现。"""
    with open(LEGACY_BOOKS_FILE, "r", encoding="utf-8") as file:
        rows = json.load(file)

    books = []

    for row in rows:
        isbn = row["isbn"] if "isbn" in row else make_isbn()
        #《三体》按文档样例固定成 5 册，在架数稍后由借阅记录扣减到 2
        total = 5 if row["book_id"] == "B001" else random.randint(3, 6)

        books.append(Book(
            book_id=row["book_id"],
            isbn=isbn,
            title=row["title"],
            author=row["author"],
            category=row["category"],
            call_number=row["call_number"],
            total_copies=total,
            available_copies=total,
            description=row["description"]
        ))

    return books


def build_random_books(existing_ids, need):
    """按类目权重造书。书名用“主题词 + 后缀”拼，保证 BM25 和向量检索都有词可搜。"""
    categories = list(CATEGORY_WEIGHTS)
    weights = [CATEGORY_WEIGHTS[name] for name in categories]

    used_titles = set()
    books = []
    serial = 0

    while len(books) < need:
        category = random.choices(categories, weights=weights, k=1)[0]
        topic = random.choice(CATEGORY_INFO[category][1])
        title = topic + random.choice(TITLE_SUFFIXES)

        if title in used_titles:
            #重名就加版本号，保证书名不重复
            title = title + "（第" + str(random.randint(2, 9)) + "版）"

        if title in used_titles:
            continue

        used_titles.add(title)
        serial += 1

        total = random.randint(2, 6)

        #从同类目的其他主题词里抽两个作为“相关主题”，让每本书的简介内容各不相同
        related = random.sample(
            [word for word in CATEGORY_INFO[category][1] if word != topic],
            k=2
        )
        description = random.choice(DESCRIPTION_TEMPLATES).format(
            topic=topic,
            rel1=related[0],
            rel2=related[1]
        )

        books.append(Book(
            book_id="B" + f"{len(existing_ids) + serial:03d}",
            isbn=make_isbn(),
            title=title,
            author=make_author(),
            category=category,
            call_number=make_call_number(category),
            total_copies=total,
            available_copies=total,
            # description="本书围绕" + topic + "展开，介绍其基本概念、典型方法与实际应用，适合作为教材或自学参考。"
            description=description
        ))

    return books


def build_users():
    levels = [name for name, _ in LEVEL_WEIGHTS]
    weights = [weight for _, weight in LEVEL_WEIGHTS]

    users = []

    for i in range(1, USER_TARGET + 1):
        level = random.choices(levels, weights=weights, k=1)[0]

        users.append(User(
            user_id="R" + str(2025000 + i),
            name=random.choice(AUTHOR_FAMILY) + random.choice(AUTHOR_GIVEN),
            phone="1" + random.choice("3456789") + "".join(random.choice("0123456789") for _ in range(8)),
            level=level,
            #额度不另写一套数字，直接取 rules.py 的规则，服务和种子共用同一个来源
            max_borrow=rules.max_borrow_for(level),
            current_borrow=0
        ))

    return users


def reset_tables(db):
    """清空 4 张表。顺序是先删“引用别人的表”，再删“被引用的表”。"""
    db.query(Reservation).delete(synchronize_session=False)
    db.query(Loan).delete(synchronize_session=False)
    db.query(User).delete(synchronize_session=False)
    db.query(Book).delete(synchronize_session=False)
    db.commit()


def seed_loans(db, books, users, now):
    """造借阅记录，并同步维护 books.available_copies 和 users.current_borrow。

    关键点：在架数不是硬编码出来的，而是“总册数 − 未归还的借阅数”算出来的。
    所以《三体》给它 3 条未归还记录之后，自然就是 5 册 2 册在架（文档第二节样例）。
    """
    loans = []
    next_no = 1

    def add_loan(book, user, borrowed_at, returned_at=None):
        nonlocal next_no

        loans.append(Loan(
            loan_id="L" + f"{next_no:06d}",
            user_id=user.user_id,
            book_id=book.book_id,
            borrowed_at=borrowed_at,
            due_at=rules.calculate_due_at(borrowed_at),
            returned_at=returned_at,
            renew_count=0
        ))
        next_no += 1

        if returned_at is None:
            #未归还才占用在架数和个人额度
            book.available_copies -= 1
            user.current_borrow += 1

    #1) 《三体》：3 条未归还记录 → 5 册里剩 2 册在架
    santi = next(book for book in books if book.book_id == "B001")

    for i in range(3):
        add_loan(santi, users[i], now - timedelta(days=10 + i * 3))

    #2) 30 条活跃借阅，前 3 条故意造成逾期（45 天前借出，应还日期已经过了 15 天）
    #《三体》不再参与随机借阅，保证样例里的 5 册 / 2 册固定
    pool = [book for book in books if book.available_copies > 0 and book.book_id != "B001"]
    random.shuffle(pool)

    for i in range(ACTIVE_LOAN_COUNT):
        if i < OVERDUE_LOAN_COUNT:
            borrowed_at = now - timedelta(days=45)
        else:
            borrowed_at = now - timedelta(days=random.randint(3, 25))

        add_loan(pool[i], users[3 + i], borrowed_at)

    #3) 10 条已经归还的历史记录（不影响在架数，只让借阅列表更真实）
    for i in range(RETURNED_LOAN_COUNT):
        borrowed_at = now - timedelta(days=60 + i)
        add_loan(pool[ACTIVE_LOAN_COUNT + 3 + i], users[ACTIVE_LOAN_COUNT + 3 + i], borrowed_at,
                 returned_at=borrowed_at + timedelta(days=20))

    db.add_all(loans)
    db.commit()

    return loans


def main():
    init_db()
    random.seed(RANDOM_SEED)

    db = SessionLocal()

    try:
        reset_tables(db)

        legacy_books = build_legacy_books()
        random_books = build_random_books(
            {book.book_id for book in legacy_books},
            BOOK_TARGET - len(legacy_books)
        )
        books = legacy_books + random_books
        users = build_users()

        db.add_all(books)
        db.add_all(users)
        db.commit()

        loans = seed_loans(db, books, users, datetime.now())

        santi = next(book for book in books if book.book_id == "B001")

        print("图书:", len(books), "本")
        print("读者:", len(users), "人")
        print("借阅记录:", len(loans), "条（其中逾期未还", OVERDUE_LOAN_COUNT, "条）")
        print("《三体》:", santi.total_copies, "册 /", santi.available_copies, "册在架")
        print("数据灌好了")
    finally:
        db.close()


if __name__ == "__main__":
    main()