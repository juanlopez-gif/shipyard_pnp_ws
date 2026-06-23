import os
import time
import urllib.parse
import urllib.request
from typing import Callable

from shipyard_pnp.shared.contracts import MachineState


class LaserAdapter:
    """
    Safe adapter for the laser vendor domain.

    Modes:
      dry_run: exercise the Plug-and-Plan contract without touching hardware.
      http: send GCODE lines to the laser HTTP endpoint used by the old node.
    """

    def __init__(
        self,
        mode: str = "dry_run",
        laser_ip: str = "192.168.0.173",
        gcode_dir: str = "/home/isecapstone/laser_gcode/",
        default_gcode: str = "happyface.gcode",
        allowed_gcode_files=None,
        blocked_gcode_fragments=None,
        wait_time_before_start_sec: float = 30.0,
        prepare_delay_sec: float = 0.2,
        job_duration_sec: float = 2.0,
        inter_command_delay_sec: float = 1.0,
        http_timeout_sec: float = 10.0,
        fail_on_gcode_error: bool = True,
        logger=None,
    ):
        self.mode = self._normalize_mode(mode)
        self.laser_ip = str(laser_ip).strip()
        self.gcode_dir = os.path.expanduser(str(gcode_dir).strip())
        self.allowed_gcode_files = self._normalize_allowed_files(
            allowed_gcode_files or ["happyface.gcode"]
        )
        self.blocked_gcode_fragments = [
            str(fragment).strip().lower()
            for fragment in (blocked_gcode_fragments or ["s25"])
            if str(fragment).strip()
        ]
        self.default_gcode = self._validate_filename(default_gcode)
        self.wait_time_before_start_sec = max(float(wait_time_before_start_sec), 0.0)
        self.prepare_delay_sec = max(float(prepare_delay_sec), 0.0)
        self.job_duration_sec = max(float(job_duration_sec), 0.0)
        self.inter_command_delay_sec = max(float(inter_command_delay_sec), 0.0)
        self.http_timeout_sec = max(float(http_timeout_sec), 0.1)
        self.fail_on_gcode_error = bool(fail_on_gcode_error)
        self._logger = logger
        self._prepared_job_type = None
        self._prepared_filename = None

    def make_task_fn(self, cmd: dict) -> Callable[[], dict]:
        task = cmd.get("task", "")
        params = cmd.get("parameters") or {}

        def fn() -> dict:
            if task == "INITIALIZE_DOMAIN":
                return self.initialize_domain()
            if task == "PREPARE_JOB":
                return self.prepare_job(
                    job_type=params.get("job_type", "DEFAULT"),
                    filename=self._filename_from_params(params),
                )
            if task in {"RUN_JOB", "WORK"}:
                return self.run_job(
                    job_type=params.get("job_type", self._prepared_job_type or "DEFAULT"),
                    filename=self._filename_from_params(params) or self._prepared_filename,
                    piece_id=cmd.get("piece_id"),
                )
            if task in {"RESET", "GET_READY_TO_WORK"}:
                return self.reset()
            raise ValueError(f"Unsupported laser task: {task}")

        return fn

    def initialize_domain(self) -> dict:
        self._info(f"Laser adapter initialized in {self.mode} mode")
        return {
            "resource_state": MachineState.IDLE.value,
            "code": "INITIALIZED",
            "mode": self.mode,
        }

    def prepare_job(self, job_type: str, filename: str = None) -> dict:
        job_type = self._normalize_job_type(job_type)
        filename = self._validate_filename(filename or self.default_gcode)
        self._prepared_job_type = job_type
        self._prepared_filename = filename
        time.sleep(self.prepare_delay_sec)
        return {
            "resource_state": MachineState.PREPARING.value,
            "code": "JOB_PREPARED",
            "job_type": job_type,
            "filename": filename,
            "mode": self.mode,
        }

    def run_job(self, job_type: str, filename: str = None, piece_id: str = None) -> dict:
        job_type = self._normalize_job_type(job_type)
        filename = self._validate_filename(filename or self.default_gcode)
        if self.mode == "http":
            return self._run_http_job(job_type, filename, piece_id)

        self._info(
            f"Laser dry-run job started: job_type={job_type}, "
            f"filename={filename}, piece_id={piece_id or ''}"
        )
        time.sleep(self.job_duration_sec)
        self._prepared_job_type = None
        self._prepared_filename = None
        return {
            "resource_state": MachineState.FINISHED.value,
            "code": "DRY_RUN_JOB_DONE",
            "job_type": job_type,
            "filename": filename,
            "piece_id": piece_id,
            "mode": self.mode,
        }

    def reset(self) -> dict:
        self._prepared_job_type = None
        self._prepared_filename = None
        return {
            "resource_state": MachineState.IDLE.value,
            "code": "RESET_DONE",
            "mode": self.mode,
        }

    def _run_http_job(self, job_type: str, filename: str, piece_id: str = None) -> dict:
        filepath = os.path.join(self.gcode_dir, filename)
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"Laser GCODE file not found: {filepath}")

        self._info(
            f"Laser HTTP job started: job_type={job_type}, "
            f"filename={filename}, piece_id={piece_id or ''}"
        )
        if self.wait_time_before_start_sec > 0:
            self._info(
                f"Laser waiting {self.wait_time_before_start_sec:.1f}s before start"
            )
            time.sleep(self.wait_time_before_start_sec)

        lines = self._read_gcode_lines(filepath)
        sent_count = 0
        error_count = 0
        for index, line in enumerate(lines, start=1):
            ok = self._send_gcode_command(line)
            if ok:
                sent_count += 1
            else:
                error_count += 1
                self._error(f"Laser HTTP command failed at line {index}")
                if self.fail_on_gcode_error:
                    raise RuntimeError(f"Laser HTTP command failed at line {index}")
            if index % 10 == 0:
                self._info(f"Laser HTTP progress {index}/{len(lines)}")

        self._prepared_job_type = None
        self._prepared_filename = None
        return {
            "resource_state": MachineState.FINISHED.value,
            "code": "JOB_DONE",
            "job_type": job_type,
            "filename": filename,
            "piece_id": piece_id,
            "mode": self.mode,
            "commands_sent": sent_count,
            "command_errors": error_count,
            "line_count": len(lines),
        }

    def _send_gcode_command(self, gcode: str) -> bool:
        encoded = urllib.parse.quote(gcode)
        url = f"http://{self.laser_ip}/command?commandText={encoded}&PAGEID=0"
        try:
            with urllib.request.urlopen(url, timeout=self.http_timeout_sec) as response:
                status_code = response.getcode()
            time.sleep(self.inter_command_delay_sec)
            return status_code == 200
        except Exception as exc:
            self._error(f"Laser HTTP request failed: {exc}")
            return False

    @staticmethod
    def _read_gcode_lines(filepath: str) -> list:
        with open(filepath) as fh:
            return [
                line.strip()
                for line in fh
                if line.strip() and not line.lstrip().startswith(";")
            ]

    def _filename_from_params(self, params: dict) -> str:
        for key in ("filename", "gcode_file", "gcode_filename"):
            value = params.get(key)
            if value:
                return self._validate_filename(value)
        return ""

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        normalized = str(mode or "dry_run").strip().lower()
        if normalized in {"dryrun", "dry-run", "sim", "simulation"}:
            return "dry_run"
        if normalized in {"real", "laser_http"}:
            return "http"
        if normalized != "dry_run":
            return normalized
        return "dry_run"

    @staticmethod
    def _normalize_job_type(job_type: str) -> str:
        normalized = str(job_type or "DEFAULT").strip().upper()
        return normalized or "DEFAULT"

    @staticmethod
    def _safe_filename(filename: str) -> str:
        normalized = os.path.basename(str(filename or "").strip())
        return normalized or "happyface.gcode"

    @classmethod
    def _normalize_allowed_files(cls, filenames) -> set:
        return {
            cls._safe_filename(filename)
            for filename in filenames
            if str(filename or "").strip()
        }

    def _validate_filename(self, filename: str) -> str:
        normalized = self._safe_filename(filename)
        lowered = normalized.lower()
        for fragment in self.blocked_gcode_fragments:
            if fragment in lowered:
                raise ValueError(
                    f"Blocked laser GCODE file '{normalized}' "
                    f"(matched blocked fragment '{fragment}')"
                )
        if self.allowed_gcode_files and normalized not in self.allowed_gcode_files:
            allowed = ", ".join(sorted(self.allowed_gcode_files))
            raise ValueError(
                f"Unsupported laser GCODE file '{normalized}'. "
                f"Allowed files: {allowed}"
            )
        return normalized

    def _info(self, msg: str) -> None:
        if self._logger is not None:
            self._logger.info(msg)

    def _error(self, msg: str) -> None:
        if self._logger is not None:
            self._logger.error(msg)
