"""Tests unitarios para fabric_catalog.py — sin acceso real a Microsoft Fabric."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from fabric_catalog import (
    classify_http_error,
    convert_time_to_tz,
    describe_schedule,
    parse_schedule_status,
    write_csv,
    write_json,
    FabricApiError,
)


# ---------------------------------------------------------------------------
# Fixtures / datos simulados
# ---------------------------------------------------------------------------

SCHEDULE_DAILY = {
    "id": "sched-daily-001",
    "enabled": True,
    "createdDateTime": "2024-05-28T05:35:20.5366667",
    "configuration": {
        "startDateTime": "2024-01-01T00:00:00Z",
        "endDateTime": "2099-12-31T23:59:00Z",
        "localTimeZoneId": "SA Pacific Standard Time",
        "type": "Daily",
        "times": ["19:00"],
    },
    "owner": {"id": "user-1", "type": "User"},
}

SCHEDULE_WEEKLY = {
    "id": "sched-weekly-001",
    "enabled": True,
    "createdDateTime": "2024-05-28T05:35:20.5366667",
    "configuration": {
        "startDateTime": "2024-01-01T00:00:00Z",
        "endDateTime": "2099-12-31T23:59:00Z",
        "localTimeZoneId": "SA Pacific Standard Time",
        "type": "Weekly",
        "weekdays": ["Monday", "Wednesday"],
        "times": ["06:30"],
    },
    "owner": {"id": "user-2", "type": "User"},
}

SCHEDULE_MONTHLY = {
    "id": "sched-monthly-001",
    "enabled": True,
    "createdDateTime": "2024-05-28T05:35:20.5366667",
    "configuration": {
        "startDateTime": "2024-01-01T00:00:00Z",
        "endDateTime": "2099-12-31T23:59:00Z",
        "localTimeZoneId": "SA Pacific Standard Time",
        "type": "Monthly",
        "occurrence": {"dayOfMonth": 15, "occurrenceType": "DayOfMonth"},
        "recurrence": 1,
        "times": ["04:00"],
    },
    "owner": {"id": "user-3", "type": "User"},
}

SCHEDULE_CRON = {
    "id": "sched-cron-001",
    "enabled": True,
    "createdDateTime": "2024-05-28T05:35:20.5366667",
    "configuration": {
        "startDateTime": "2024-01-01T00:00:00Z",
        "endDateTime": "2099-12-31T23:59:00Z",
        "localTimeZoneId": "SA Pacific Standard Time",
        "type": "Cron",
        "interval": 10,
    },
    "owner": {"id": "user-4", "type": "User"},
}

SCHEDULE_DISABLED = {
    "id": "sched-disabled-001",
    "enabled": False,
    "createdDateTime": "2024-05-28T05:35:20.5366667",
    "configuration": {
        "startDateTime": "2024-01-01T00:00:00Z",
        "endDateTime": "2024-06-30T23:59:00Z",
        "localTimeZoneId": "SA Pacific Standard Time",
        "type": "Daily",
        "times": ["02:00"],
    },
    "owner": {"id": "user-5", "type": "User"},
}

SCHEDULE_EXPIRED = {
    "id": "sched-expired-001",
    "enabled": True,
    "createdDateTime": "2024-01-01T00:00:00Z",
    "configuration": {
        "startDateTime": "2024-01-01T00:00:00Z",
        "endDateTime": "2024-06-30T23:59:00Z",
        "localTimeZoneId": "SA Pacific Standard Time",
        "type": "Daily",
        "times": ["03:00"],
    },
    "owner": {"id": "user-6", "type": "User"},
}

SCHEDULE_UNKNOWN = {
    "id": "sched-unknown-001",
    "enabled": True,
    "createdDateTime": "2024-05-28T05:35:20.5366667",
    "configuration": {
        "startDateTime": "2024-01-01T00:00:00Z",
        "endDateTime": "2099-12-31T23:59:00Z",
        "localTimeZoneId": "SA Pacific Standard Time",
        "type": "SomethingNew",
        "foo": "bar",
    },
    "owner": {"id": "user-7", "type": "User"},
}

SCHEDULE_MONTHLY_ORDINAL = {
    "id": "sched-monthly-ordinal-001",
    "enabled": True,
    "createdDateTime": "2024-05-28T05:35:20.5366667",
    "configuration": {
        "startDateTime": "2024-01-01T00:00:00Z",
        "endDateTime": "2099-12-31T23:59:00Z",
        "localTimeZoneId": "SA Pacific Standard Time",
        "type": "Monthly",
        "occurrence": {
            "occurrenceType": "OrdinalWeekday",
            "weekIndex": "First",
            "weekday": "Monday",
        },
        "recurrence": 1,
        "times": ["08:00"],
    },
    "owner": {"id": "user-8", "type": "User"},
}

SCHEDULE_WEEKLY_WEEKEND = {
    "id": "sched-weekly-weekend-001",
    "enabled": True,
    "createdDateTime": "2024-05-28T05:35:20.5366667",
    "configuration": {
        "startDateTime": "2024-01-01T00:00:00Z",
        "endDateTime": "2099-12-31T23:59:00Z",
        "localTimeZoneId": "SA Pacific Standard Time",
        "type": "Weekly",
        "weekdays": ["Saturday", "Sunday"],
        "times": ["10:00"],
    },
    "owner": {"id": "user-9", "type": "User"},
}

SCHEDULE_WEEKLY_MONDAY_FRIDAY = {
    "id": "sched-weekly-mf-001",
    "enabled": True,
    "createdDateTime": "2024-05-28T05:35:20.5366667",
    "configuration": {
        "startDateTime": "2024-01-01T00:00:00Z",
        "endDateTime": "2099-12-31T23:59:00Z",
        "localTimeZoneId": "SA Pacific Standard Time",
        "type": "Weekly",
        "weekdays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "times": ["02:00"],
    },
    "owner": {"id": "user-10", "type": "User"},
}


# ---------------------------------------------------------------------------
# describe_schedule
# ---------------------------------------------------------------------------

class TestDescribeSchedule:
    def test_daily(self):
        desc = describe_schedule(SCHEDULE_DAILY["configuration"])
        assert "Todos los días" in desc
        assert "19:00" in desc

    def test_weekly_lunes_miercoles(self):
        desc = describe_schedule(SCHEDULE_WEEKLY["configuration"])
        assert "lunes y miércoles" in desc.lower()
        assert "06:30" in desc

    def test_weekly_monday_friday_range(self):
        desc = describe_schedule(SCHEDULE_WEEKLY_MONDAY_FRIDAY["configuration"])
        assert "de lunes a viernes" in desc.lower()
        assert "02:00" in desc

    def test_weekly_weekend(self):
        desc = describe_schedule(SCHEDULE_WEEKLY_WEEKEND["configuration"])
        assert "fines de semana" in desc.lower()
        assert "10:00" in desc

    def test_monthly_day_of_month(self):
        desc = describe_schedule(SCHEDULE_MONTHLY["configuration"])
        assert "día 15" in desc
        assert "cada mes" in desc
        assert "04:00" in desc

    def test_monthly_ordinal_weekday(self):
        desc = describe_schedule(SCHEDULE_MONTHLY_ORDINAL["configuration"])
        assert "primer lunes" in desc.lower()
        assert "08:00" in desc

    def test_monthly_recurrence_interval(self):
        cfg = dict(SCHEDULE_MONTHLY["configuration"], recurrence=3)
        desc = describe_schedule(cfg)
        assert "cada 3 meses" in desc

    def test_cron(self):
        desc = describe_schedule(SCHEDULE_CRON["configuration"])
        assert "10" in desc
        assert "minutos" in desc

    def test_unknown_type(self):
        desc = describe_schedule(SCHEDULE_UNKNOWN["configuration"])
        assert desc == "Configuración no interpretada"

    def test_multiple_times(self):
        cfg = dict(SCHEDULE_DAILY["configuration"], times=["02:00", "14:00"])
        desc = describe_schedule(cfg)
        assert "02:00" in desc
        assert "14:00" in desc

    def test_missing_times(self):
        cfg = {"type": "Daily", "localTimeZoneId": "UTC"}
        desc = describe_schedule(cfg)
        assert "Todos los días" in desc


# ---------------------------------------------------------------------------
# parse_schedule_status
# ---------------------------------------------------------------------------

class TestParseScheduleStatus:
    def test_enabled(self):
        now = datetime(2025, 6, 1, tzinfo=timezone.utc)
        assert parse_schedule_status(SCHEDULE_DAILY, now) == "habilitada"

    def test_disabled(self):
        now = datetime(2025, 6, 1, tzinfo=timezone.utc)
        assert parse_schedule_status(SCHEDULE_DISABLED, now) == "deshabilitada"

    def test_expired(self):
        now = datetime(2025, 6, 1, tzinfo=timezone.utc)
        assert parse_schedule_status(SCHEDULE_EXPIRED, now) == "vencida"

    def test_no_end_date_still_enabled(self):
        cfg = dict(SCHEDULE_DAILY["configuration"])
        cfg.pop("endDateTime")
        sched = dict(SCHEDULE_DAILY, configuration=cfg)
        now = datetime(2025, 6, 1, tzinfo=timezone.utc)
        assert parse_schedule_status(sched, now) == "habilitada"

    def test_enabled_false_overrides_end_date(self):
        now = datetime(2025, 6, 1, tzinfo=timezone.utc)
        assert parse_schedule_status(SCHEDULE_DISABLED, now) == "deshabilitada"


# ---------------------------------------------------------------------------
# convert_time_to_tz
# ---------------------------------------------------------------------------

class TestConvertTimeToTz:
    def test_valid_conversion(self):
        r = convert_time_to_tz("19:00", "SA Pacific Standard Time", "America/Bogota")
        assert r["conversionOk"] is True
        assert r["convertedTime"] == "19:00"
        assert r["convertedTz"] == "America/Bogota"

    def test_invalid_tz(self):
        r = convert_time_to_tz("19:00", "SA Pacific Standard Time", "Not/AZone")
        assert r["conversionOk"] is False
        assert r["convertedTime"] == ""

    def test_invalid_time_format(self):
        r = convert_time_to_tz("not-a-time", "UTC", "America/Bogota")
        assert r["conversionOk"] is False


# ---------------------------------------------------------------------------
# classify_http_error
# ---------------------------------------------------------------------------

class TestClassifyHttpError:
    def test_401(self):
        assert classify_http_error(401) == "unauthorized"

    def test_403(self):
        assert classify_http_error(403) == "forbidden"

    def test_404(self):
        assert classify_http_error(404) == "not_found"

    def test_429(self):
        assert classify_http_error(429) == "rate_limited"

    def test_500(self):
        assert classify_http_error(500) == "server_error"

    def test_503(self):
        assert classify_http_error(503) == "server_error"

    def test_400(self):
        assert classify_http_error(400) == "http_error"


# ---------------------------------------------------------------------------
# Fabric.paged con continuación
# ---------------------------------------------------------------------------

class TestPagedPagination:
    def _make_fab(self, responses):
        fab = MagicMock()
        fab.paged = None
        from fabric_catalog import Fabric
        fake_cred = MagicMock()
        fake_cred.get_token.return_value.token = "tok"
        f = Fabric.__new__(Fabric)
        f.cred = fake_cred
        f.s = MagicMock()

        call_count = [0]
        def fake_request(method, url, **kw):
            idx = call_count[0]
            call_count[0] += 1
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = responses[idx]
            resp.raise_for_status = MagicMock()
            return resp
        f.request = fake_request
        return f

    def test_single_page(self):
        fab = self._make_fab([{"value": [{"id": 1}], "continuationToken": None}])
        out = fab.paged("/test")
        assert out == [{"id": 1}]

    def test_multi_page_with_token(self):
        fab = self._make_fab([
            {"value": [{"id": 1}], "continuationToken": "tok1"},
            {"value": [{"id": 2}]},
        ])
        out = fab.paged("/test")
        assert len(out) == 2
        assert out[0]["id"] == 1
        assert out[1]["id"] == 2

    def test_multi_page_with_continuation_uri(self):
        fab = self._make_fab([
            {"value": [{"id": 1}], "continuationUri": "https://api.fabric.microsoft.com/v1/test?page=2"},
            {"value": [{"id": 2}]},
        ])
        out = fab.paged("/test")
        assert len(out) == 2

    def test_limit(self):
        fab = self._make_fab([
            {"value": [{"id": 1}, {"id": 2}, {"id": 3}], "continuationToken": "tok1"},
        ])
        out = fab.paged("/test", limit=2)
        assert len(out) == 2


# ---------------------------------------------------------------------------
# FabricApiError
# ---------------------------------------------------------------------------

class TestFabricApiError:
    def test_attributes(self):
        e = FabricApiError(403, "No permisos", "InsufficientPrivileges")
        assert e.status == 403
        assert e.error_code == "InsufficientPrivileges"
        assert "403" in str(e)

    def test_inheritance(self):
        assert issubclass(FabricApiError, Exception)


# ---------------------------------------------------------------------------
# Exportación CSV / JSON con caracteres españoles
# ---------------------------------------------------------------------------

class TestExport:
    def test_csv_utf8_spanish(self, tmp_path):
        rows = [
            {"nombre": "Pipeline ETL Ñandú", "estado": "habilitada", "desc": "Todos los días a las 19:00"},
            {"nombre": "Reporte Métricas", "estado": "vencida", "desc": "lunes y miércoles a las 06:30"},
        ]
        p = tmp_path / "test.csv"
        write_csv(p, rows)
        content = p.read_text(encoding="utf-8-sig")
        assert "Ñandú" in content
        assert "Métricas" in content
        assert "habilitada" in content

    def test_csv_empty(self, tmp_path):
        p = tmp_path / "empty.csv"
        write_csv(p, [])
        assert not p.exists()

    def test_json_utf8(self, tmp_path):
        data = [{"nombre": "Pipeline Ñandú", "desc": "Todos los días"}]
        p = tmp_path / "test.json"
        write_json(p, data)
        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert loaded[0]["nombre"] == "Pipeline Ñandú"


# ---------------------------------------------------------------------------
# Compatibilidad: salidas anteriores se mantienen
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_catalog_row_fields(self):
        row = {
            "workspace": "Prod", "workspaceId": "ws-1",
            "capacityId": "cap-1",
            "itemType": "DataPipeline", "itemName": "ETL Diario",
            "itemId": "item-1", "description": "",
        }
        assert set(row.keys()) == {
            "workspace", "workspaceId", "capacityId",
            "itemType", "itemName", "itemId", "description",
        }

    def test_schedule_row_min_fields(self):
        row = {
            "workspaceName": "Prod", "workspaceId": "ws-1",
            "pipelineName": "ETL", "pipelineId": "p-1",
            "scheduleId": "s-1", "scheduleEnabled": True,
            "scheduleStatus": "habilitada",
            "scheduleType": "Daily",
            "scheduleDescription": "Todos los días a las 19:00",
            "startDateTime": "2024-01-01T00:00:00Z",
            "endDateTime": "2099-12-31T23:59:00Z",
            "localTimeZoneId": "SA Pacific Standard Time",
            "ownerId": "u-1", "ownerType": "User",
            "createdDateTime": "2024-05-28T05:35:20",
            "configurationJson": "{}",
            "collectionStatus": "ok",
            "collectedAtUtc": "2025-01-01T00:00:00+00:00",
        }
        required = {
            "workspaceName", "workspaceId", "pipelineName", "pipelineId",
            "scheduleId", "scheduleEnabled", "scheduleType", "scheduleDescription",
            "startDateTime", "endDateTime", "localTimeZoneId",
            "ownerId", "ownerType", "createdDateTime",
            "configurationJson", "collectionStatus", "collectedAtUtc",
        }
        assert required.issubset(row.keys())


# ---------------------------------------------------------------------------
# Scenarios: pipeline con varias programaciones
# ---------------------------------------------------------------------------

class TestMultiSchedulePipeline:
    def test_three_schedules_one_pipeline(self):
        schedules = [SCHEDULE_DAILY, SCHEDULE_WEEKLY, SCHEDULE_MONTHLY]
        assert len(schedules) == 3
        ids = [s["id"] for s in schedules]
        assert len(set(ids)) == 3

    def test_descriptions_are_distinct(self):
        schedules = [SCHEDULE_DAILY, SCHEDULE_WEEKLY, SCHEDULE_MONTHLY]
        descs = [describe_schedule(s["configuration"]) for s in schedules]
        assert len(set(descs)) == 3
