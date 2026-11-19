"""Shared return normalization and fixed seven-way decision boundaries."""
from __future__ import annotations

import math

HORIZONS = (1, 5, 20)
ZERO_LOG_RETURN_TOLERANCE = 1e-12


def class_id_for_z(z: float) -> int:
    if not math.isfinite(z):
        raise ValueError("Class requires finite Z")
    if z == 0:
        return 3
    if z < 0:
        return sum(z >= edge for edge in (-1.5, -0.5))
    return 4 + sum(z > edge for edge in (0.5, 1.5))


def install_return_macros(con):
    con.execute("""
        CREATE OR REPLACE TEMP MACRO kurumi_zero(x) AS
            CASE WHEN abs(x) <= 1e-12 THEN 0.0::DOUBLE ELSE x END;
        CREATE OR REPLACE TEMP MACRO kurumi_log_ratio(finish, start) AS
            CASE WHEN isfinite(finish) AND isfinite(start) AND finish > 0 AND start > 0
                 THEN kurumi_zero(ln(finish / start)) END;
        CREATE OR REPLACE TEMP MACRO kurumi_expm1(x) AS
            CASE WHEN abs(x) < 0.001
                 THEN x * (1 + x * (0.5 + x * (1.0/6 + x * (1.0/24 + x * (1.0/120 + x / 720)))))
                 ELSE exp(x) - 1 END;
        CREATE OR REPLACE TEMP MACRO kurumi_log1p(x) AS
            kurumi_log_ratio(1 + x, 1.0);
        CREATE OR REPLACE TEMP MACRO kurumi_class(z) AS
            CASE WHEN z IS NULL OR NOT isfinite(z) THEN NULL
                 WHEN z < -1.5 THEN 0 WHEN z < -0.5 THEN 1 WHEN z < 0 THEN 2
                 WHEN z = 0 THEN 3 WHEN z <= 0.5 THEN 4 WHEN z <= 1.5 THEN 5
                 ELSE 6 END::TINYINT;
    """)
