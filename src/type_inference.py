from datetime import date, datetime
from decimal import Decimal
import re


def is_empty(value):
    return value is None or str(value).strip() == ""


def is_integer(value):
    if isinstance(value, bool):
        return False

    if isinstance(value, int):
        return True

    if isinstance(value, float):
        return value.is_integer()

    text = str(value).strip()

    return bool(re.fullmatch(r"-?\d+", text))


def is_decimal(value):
    if isinstance(value, bool):
        return False

    if isinstance(value, (int, float, Decimal)):
        return True

    text = str(value).strip()

    return bool(
        re.fullmatch(
            r"-?\d+(?:\.\d+)?",
            text
        )
    )


def looks_like_identifier(values):
    """
    防止这些数据被错误识别成数字：
    00123
    0123456789
    手机号
    身份证号
    订单号
    编号等
    """

    non_empty = [
        str(v).strip()
        for v in values
        if not is_empty(v)
    ]

    if not non_empty:
        return False

    # 出现前导 0
    if any(
        re.fullmatch(r"0\d+", v)
        for v in non_empty
    ):
        return True

    # 全部都是纯数字，但长度比较像编号
    lengths = {len(v) for v in non_empty}

    if len(lengths) == 1:
        length = next(iter(lengths))

        # 6 位以上且长度高度一致，谨慎当作编号
        if length >= 6:
            return True

    return False


def infer_column_type(values):
    non_empty = [
        v for v in values
        if not is_empty(v)
    ]

    if not non_empty:
        return "text"

    # 已经是 Python 日期/时间对象
    if all(isinstance(v, datetime) for v in non_empty):
        return "timestamp"

    if all(isinstance(v, date) for v in non_empty):
        return "date"

    # Boolean
    boolean_values = {
        "true",
        "false",
        "yes",
        "no",
        "是",
        "否",
        "是的",
        "否的",
    }

    if all(
        isinstance(v, bool)
        or str(v).strip().lower() in boolean_values
        for v in non_empty
    ):
        return "boolean"

    # 身份证、手机号、订单号、编号等
    if looks_like_identifier(non_empty):
        return "text"

    # 整数
    if all(is_integer(v) for v in non_empty):
        max_value = max(
            abs(int(float(v)))
            for v in non_empty
        )

        if max_value <= 2147483647:
            return "integer"

        if max_value <= 9223372036854775807:
            return "bigint"

        return "numeric"

    # 小数
    if all(is_decimal(v) for v in non_empty):
        return "numeric"

    # 日期字符串
    date_patterns = [
        r"^\d{4}-\d{1,2}-\d{1,2}$",
        r"^\d{4}/\d{1,2}/\d{1,2}$",
        r"^\d{4}\.\d{1,2}\.\d{1,2}$",
    ]

    if all(
        any(
            re.fullmatch(pattern, str(v).strip())
            for pattern in date_patterns
        )
        for v in non_empty
    ):
        return "date"

    # 时间戳字符串
    timestamp_patterns = [
        r"^\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{1,2}(:\d{1,2})?$",
        r"^\d{4}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{1,2}(:\d{1,2})?$",
    ]

    if all(
        any(
            re.fullmatch(pattern, str(v).strip())
            for pattern in timestamp_patterns
        )
        for v in non_empty
    ):
        return "timestamp"

    # 其他全部按文本处理
    return "text"


def infer_sheet_types(ws, header_row):
    headers = [
        str(cell.value).strip()
        if cell.value is not None
        else ""
        for cell in ws[header_row]
    ]

    result = []

    for column_index, header in enumerate(headers, start=1):

        values = []

        for row in ws.iter_rows(
            min_row=header_row + 1,
            min_col=column_index,
            max_col=column_index,
            values_only=True,
        ):
            values.append(row[0])

        pg_type = infer_column_type(values)

        result.append(
            {
                "column": column_index,
                "header": header,
                "postgres_type": pg_type,
            }
        )

    return result
