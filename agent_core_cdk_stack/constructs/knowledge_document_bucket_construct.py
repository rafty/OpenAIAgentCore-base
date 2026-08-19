"""Managed Knowledge Base向け文書bucketと配置resourceを定義する。"""

from pathlib import Path

from aws_cdk import RemovalPolicy
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3_deployment
from constructs import Construct


KNOWLEDGE_DOCUMENT_PATHS = frozenset(
    {
        "estimation/estimation_guideline.md",
        "estimation/estimation_guideline.md.metadata.json",
        "projects/sample_project_alpha.md",
        "projects/sample_project_alpha.md.metadata.json",
        "standards/aws_architecture_standard.md",
        "standards/aws_architecture_standard.md.metadata.json",
        "standards/monitoring_standard.md",
        "standards/monitoring_standard.md.metadata.json",
        "standards/security_standard.md",
        "standards/security_standard.md.metadata.json",
    }
)
KNOWLEDGE_DOCUMENTS_DIRECTORY = (
    Path(__file__).resolve().parents[2] / "knowledge-base-s3"
)


class KnowledgeDocumentBucketConstruct(Construct):
    """検証済みナレッジ文書だけを専用S3バケットへ配置する。"""

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        self.source_directory = KNOWLEDGE_DOCUMENTS_DIRECTORY
        _validate_knowledge_documents(self.source_directory)

        self.bucket = s3.Bucket(
            self,
            "Bucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            auto_delete_objects=True,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # pruneはdestination rootにあるobjectを削除し得る。ここではbucketを
        # ナレッジ文書だけの専用品に限定することで、ローカル削除を安全に反映する。
        self.deployment = s3_deployment.BucketDeployment(
            self,
            "Deployment",
            sources=[s3_deployment.Source.asset(str(self.source_directory))],
            destination_bucket=self.bucket,
            prune=True,
            retain_on_delete=False,
        )


def _validate_knowledge_documents(directory: Path) -> None:
    """登録対象の欠落や生成物混入をCloudFormation生成前に拒否する。"""

    if not directory.is_dir():
        raise ValueError("ナレッジ文書ディレクトリを読み込めません。")

    # allowlistと完全一致させることで、除外patternの更新漏れによる内部文書や
    # ローカル生成物の意図しない取り込みを防ぐ。
    actual_paths = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file()
    }
    if actual_paths != KNOWLEDGE_DOCUMENT_PATHS:
        raise ValueError("ナレッジ文書の登録対象が仕様と一致しません。")

    markdown_paths = {path for path in actual_paths if path.endswith(".md")}
    metadata_paths = {
        path for path in actual_paths if path.endswith(".md.metadata.json")
    }
    expected_metadata_paths = {f"{path}.metadata.json" for path in markdown_paths}
    if len(markdown_paths) != 5 or metadata_paths != expected_metadata_paths:
        raise ValueError("ナレッジ文書とmetadataが一対一ではありません。")
