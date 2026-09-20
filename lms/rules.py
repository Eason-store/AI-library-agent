from datetime import timedelta


# ===== 文档 3.1：借阅业务规则（写死在服务端，Agent 不需要判断）=====

LOAN_DAYS = 30               #借期 30 天
RENEW_DAYS = 30              #每次续借加 30 天
MAX_RENEW_COUNT = 1          #每本最多续借 1 次
RESERVATION_HOLD_DAYS = 3    #预约 3 天内未取书自动失效
FINE_PER_DAY = 0.0           #本档没有规定罚金标准，先固定 0；将来改这一行即可

#文档 3.1：普通读者 5 本 / 学生 8 本 / 教师 15 本
MAX_BORROW_BY_LEVEL = {
    "普通": 5,
    "学生": 8,
    "教师": 15
}


def max_borrow_for(level):
    #按读者等级给出可借上限；等级不认识时按普通读者处理（seed.py 用它给读者写 max_borrow）
    return MAX_BORROW_BY_LEVEL.get(level, MAX_BORROW_BY_LEVEL["普通"])


def calculate_due_at(borrowed_at):
    #借书：应还日期 = 借出时间 + 30 天
    return borrowed_at + timedelta(days=LOAN_DAYS)


def calculate_new_due_at(due_at):
    #续借：新应还日期 = 原应还日期 + 30 天
    return due_at + timedelta(days=RENEW_DAYS)


def is_overdue(loan, now):
    #没还、并且已经过了应还时间，就是逾期
    return loan.returned_at is None and loan.due_at < now


def check_can_borrow(user, active_loans, now):
    """借书前的规则检查。返回 (True, "") 表示允许，(False, reason) 表示拒绝及原因。
    user.max_borrow 是这个读者当前的额度（seed.py 按等级写好），active_loans 是他当前未归还的借阅。
    """
    if user.current_borrow >= user.max_borrow:
        return False, "borrow_limit_exceeded"

    #文档 3.1：逾期未还者禁止新借
    if any(is_overdue(loan, now) for loan in active_loans):
        return False, "has_overdue_loan"

    return True, ""


def check_can_renew(loan, now):
    """续借前的规则检查。
    文档 3.1 只写了“逾期未还者禁止新借”，没有禁止逾期续借，所以这里不检查逾期。
    """
    if loan.returned_at is not None:
        return False, "already_returned"

    if loan.renew_count >= MAX_RENEW_COUNT:
        return False, "renew_limit_reached"

    return True, ""


def calculate_fine(loan, returned_at):
    #逾期罚金 = 逾期天数 × 每日罚金。当前每日罚金是 0，所以结果恒为 0.0
    if returned_at <= loan.due_at:
        return 0.0

    overdue_days = (returned_at.date() - loan.due_at.date()).days

    return round(overdue_days * FINE_PER_DAY, 2)


def is_reservation_expired(reservation, now):
    #预约 3 天内未取书自动失效，只对还在 waiting 的预约判断
    if reservation.status != "waiting":
        return False

    return now >= reservation.created_at + timedelta(days=RESERVATION_HOLD_DAYS)




#"书架位置"的推导
#中图法分类号首字母 → 书架位置（文档 3.1 的 books 表没有位置字段，位置由索书号推导）
SHELF_BY_CLASS = {
    "B": "二楼哲学宗教区",
    "F": "三楼经济管理区",
    "I": "四楼文学区",
    "J": "四楼艺术区",
    "K": "五楼历史地理区",
    "N": "一楼科普区",
    "P": "一楼科普区",
    "T": "三楼计算机区"
}


def shelf_location(call_number):
    #按索书号首字母判断书架；认不出的分类统一放一楼综合书库
    if not call_number:
        return "一楼综合书库"

    return SHELF_BY_CLASS.get(call_number[0].upper(), "一楼综合书库")