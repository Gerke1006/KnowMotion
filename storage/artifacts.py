"""Local and S3-compatible artifact stores with confined object names."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
import shutil


def object_key(job_id: str, name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
        raise ValueError("Invalid job ID")
    parts = PurePosixPath(name).parts
    if not parts or name.startswith("/") or "\\" in name or ":" in name or any(p in {"..", "."} for p in parts):
        raise ValueError("Invalid artifact name")
    return f"{job_id}/{'/'.join(parts)}"


class LocalArtifactStore:
    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def get_path(self, job_id: str, name: str) -> Path:
        path = (self.root / object_key(job_id, name)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Artifact path escapes storage root")
        return path

    def put_file(self, job_id: str, name: str, source: Path | str) -> str:
        target = self.get_path(job_id, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if Path(source).resolve() != target:
            shutil.copyfile(source, target)
        return str(target)


class S3ArtifactStore:
    """Works with AWS S3 or MinIO; credentials use boto3's normal environment chain."""

    def __init__(self, bucket: str, *, endpoint_url: str | None = None, region: str | None = None, client=None):
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError("Install the storage extra to enable S3/MinIO") from exc
            client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region)
        self.client = client
        self.bucket = bucket

    def put_file(self, job_id: str, name: str, source: Path | str) -> str:
        key = object_key(job_id, name)
        self.client.upload_file(str(source), self.bucket, key)
        return f"s3://{self.bucket}/{key}"

    def download_file(self, job_id: str, name: str, destination: Path | str) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, object_key(job_id, name), str(target))
        return target

    def presigned_url(self, job_id: str, name: str, expires: int = 900) -> str:
        return self.client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": object_key(job_id, name)}, ExpiresIn=expires)
