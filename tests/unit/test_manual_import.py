# pyright: reportMissingTypeStubs=false
import sqlite3
from pathlib import Path
from typing import cast

from mocnghe.ingestion.manual import import_jd_file, import_jd_text
from mocnghe.storage.repository import CareerRepository

SYNTHETIC_JD = """
Tiêu đề: Lập trình viên C++/C#
Công ty: Công ty Ví dụ
Địa điểm: Thành phố Hồ Chí Minh
Loại hình: Toàn thời gian
Lương: Thỏa thuận

Mô tả:
Xây dựng công cụ nội bộ bằng C++ và C# cho đội vận hành tại Việt Nam.

Yêu cầu:
Ứng viên giao tiếp tiếng Việt rõ ràng, không yêu cầu bằng cấp nếu có kinh nghiệm phù hợp.
""".strip()


def test_manual_import_deduplicates_identical_text(tmp_path: Path) -> None:
    repository = CareerRepository(tmp_path / "workspace")
    repository.initialize()

    first = import_jd_text(repository, SYNTHETIC_JD, source_identity="synthetic-paste")
    second = import_jd_text(repository, SYNTHETIC_JD, source_identity="synthetic-paste")
    jobs = repository.list_jobs()

    assert first.job_id == second.job_id
    assert len(jobs) == 1
    assert jobs[0].applied is False
    assert jobs[0].source.source_id == "manual:synthetic-paste"


def test_manual_import_preserves_vietnamese_and_cpp_tokens(tmp_path: Path) -> None:
    repository = CareerRepository(tmp_path / "workspace")
    repository.initialize()

    imported = import_jd_text(repository, SYNTHETIC_JD, source_identity="synthetic-file")
    assert imported.job_id is not None
    stored = repository.get_job(imported.job_id)

    assert stored is not None
    assert stored.title == "Lập trình viên C++/C#"
    assert "Thành phố Hồ Chí Minh" in stored.location
    assert "C++" in stored.description
    assert "C#" in stored.description
    assert stored.salary.kind.value == "negotiable"


def test_manual_import_preserves_explicit_unknown_salary(tmp_path: Path) -> None:
    repository = CareerRepository(tmp_path / "workspace")
    repository.initialize()
    jd = SYNTHETIC_JD.replace("Lương: Thỏa thuận", "Lương: Chưa rõ")

    imported = import_jd_text(repository, jd, source_identity="synthetic-unknown-salary")

    assert imported.salary.kind.value == "unknown"


def _source_observation_rows(repository: CareerRepository) -> list[sqlite3.Row]:
    with repository.connect() as connection:
        table_rows = cast(
            list[sqlite3.Row],
            connection.execute(
                "select name from sqlite_master where type = 'table' order by name"
            ).fetchall(),
        )
        tables = [cast(str, row["name"]) for row in table_rows]
        for table in tables:
            column_rows = cast(
                list[sqlite3.Row], connection.execute(f"pragma table_info({table})").fetchall()
            )
            columns = {cast(str, row["name"]) for row in column_rows}
            required_columns = {"job_id", "source_identity", "raw_content", "retrieved_at"}
            provenance_columns = {"source_id", "original_uri"}
            if required_columns.issubset(columns) and provenance_columns.intersection(columns):
                return cast(
                    list[sqlite3.Row],
                    connection.execute(
                        f"select * from {table} order by retrieved_at, source_identity"
                    ).fetchall(),
                )
    return []


def test_manual_import_deduplicates_copied_renamed_files_but_keeps_source_observations(
    tmp_path: Path,
) -> None:
    repository = CareerRepository(tmp_path / "workspace")
    repository.initialize()
    first_file = tmp_path / "retail-cashier-jd.txt"
    renamed_file = tmp_path / "copied-renamed-cashier-jd.txt"
    non_tech_jd = """
Tiêu đề: Nhân viên thu ngân
Công ty: Siêu thị Ví dụ
Địa điểm: Cần Thơ
Loại hình: Toàn thời gian
Lương: Chưa rõ

Mô tả: Tính tiền và hỗ trợ khách mua hàng tại quầy.
Yêu cầu: Trung thực, giao tiếp tiếng Việt lịch sự.
""".strip()
    _ = first_file.write_text(non_tech_jd, encoding="utf-8")
    _ = renamed_file.write_text(non_tech_jd, encoding="utf-8")

    first = import_jd_file(repository, first_file)
    second = import_jd_file(repository, renamed_file)
    jobs = repository.list_jobs()
    observations = _source_observation_rows(repository)

    assert first.job_id == second.job_id
    assert len(jobs) == 1
    assert len(observations) == 2
    assert {row["source_identity"] for row in observations} == {
        str(first_file.resolve()),
        str(renamed_file.resolve()),
    }
    assert [row["raw_content"] for row in observations] == [non_tech_jd, non_tech_jd]
    assert all(row["retrieved_at"] for row in observations)
    assert {row["job_id"] for row in observations} == {first.job_id}


def test_manual_import_salary_zero_and_ambiguous_salary_parsing(tmp_path: Path) -> None:
    repository = CareerRepository(tmp_path / "workspace")
    repository.initialize()
    zero_salary_jd = SYNTHETIC_JD.replace("Lương: Thỏa thuận", "Lương: 0 VND/tháng")
    ambiguous_salary_jd = SYNTHETIC_JD.replace("Lương: Thỏa thuận", "Lương: 15")

    zero_salary = import_jd_text(repository, zero_salary_jd, source_identity="zero-salary")
    ambiguous_salary = import_jd_text(
        repository, ambiguous_salary_jd, source_identity="ambiguous-salary"
    )

    assert zero_salary.salary.kind.value == "zero"
    assert zero_salary.salary.currency == "VND"
    assert zero_salary.salary.period == "month"
    assert zero_salary.salary.minimum == 0
    assert zero_salary.salary.maximum == 0
    assert ambiguous_salary.salary.kind.value == "unknown"
    assert ambiguous_salary.salary.currency is None
    assert ambiguous_salary.salary.period is None
    assert ambiguous_salary.salary.minimum is None
    assert ambiguous_salary.salary.maximum is None
    assert ambiguous_salary.salary.gross_net == "unknown"


def test_manual_import_supports_common_vietnamese_labels_multiline_metadata_and_benefits(
    tmp_path: Path,
) -> None:
    repository = CareerRepository(tmp_path / "workspace")
    repository.initialize()
    jd = """
Tiêu đề:
  Nhân viên bán hàng
  ca tối
Công ty:
  Cửa hàng Gia dụng Ví dụ
Địa điểm:
  Quận 3
  Thành phố Hồ Chí Minh
Loại hình: Bán thời gian
Lương: Chưa rõ

Mô tả công việc:
Tư vấn khách mua sản phẩm gia dụng.
Ghi nhận tồn kho cuối ca.

Yêu cầu công việc:
Giao tiếp tiếng Việt rõ ràng.
Có thể làm cuối tuần.

Quyền lợi:
Phụ cấp gửi xe.
Đào tạo sản phẩm tại cửa hàng.

Ghi chú tự do không có nhãn: ưu tiên ứng viên gần cửa hàng.
    """.strip()

    imported = import_jd_text(repository, jd, source_identity="non-tech-vietnamese-labels")
    assert imported.job_id is not None
    stored = repository.get_job(imported.job_id)
    with repository.connect() as connection:
        raw_row = cast(
            sqlite3.Row,
            connection.execute(
                "select raw_content from jobs where job_id = ?", (imported.job_id,)
            ).fetchone(),
        )
        raw_content = cast(str, raw_row["raw_content"])

    assert stored is not None
    assert imported.title == "Nhân viên bán hàng\nca tối"
    assert imported.employer == "Cửa hàng Gia dụng Ví dụ"
    assert imported.location == "Quận 3\nThành phố Hồ Chí Minh"
    assert imported.employment_type.value == "part_time"
    assert imported.description == "Tư vấn khách mua sản phẩm gia dụng.\nGhi nhận tồn kho cuối ca."
    assert imported.requirements == "Giao tiếp tiếng Việt rõ ràng.\nCó thể làm cuối tuần."
    assert imported.benefits == "Phụ cấp gửi xe.\nĐào tạo sản phẩm tại cửa hàng."
    assert imported.freeform_text == "Ghi chú tự do không có nhãn: ưu tiên ứng viên gần cửa hàng."
    assert stored.benefits == imported.benefits
    assert stored.freeform_text == imported.freeform_text
    assert raw_content == jd
