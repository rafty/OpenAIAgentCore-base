"""Estimation境界で外部依存や入力不正を安全な状態へ変換する例外。"""


class EstimationError(Exception):
    """利用者向け契約へ安全に変換できる業務例外。"""

    status = "INTERNAL_ERROR"


class ValidationError(EstimationError):
    """入力、Schema、マスターの検証に失敗したことを表す。"""

    status = "VALIDATION_ERROR"


class ContextInvalidError(EstimationError):
    """検索コンテキストまたは候補参照が不正であることを表す。"""

    status = "CONTEXT_INVALID"


class ContextExpiredError(EstimationError):
    """検索コンテキストが論理的な期限を過ぎたことを表す。"""

    status = "CONTEXT_EXPIRED"


class NotFoundError(EstimationError):
    """完全キーで指定されたデータが存在しないことを表す。"""

    status = "NOT_FOUND"


class DependencyUnavailableError(EstimationError):
    """Bedrock、DynamoDB、Gatewayなどの依存先が利用不能であることを表す。"""

    status = "DEPENDENCY_UNAVAILABLE"


class SaveFailedError(EstimationError):
    """Draftの保存または保存後再読を成功と確認できないことを表す。"""

    status = "SAVE_FAILED"
