from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Optional

import pyodbc


@dataclass
class ClientPekcStatus:
    cod_cliente: str
    nome_cliente: str
    itens_positivados: int
    itens_faltantes: int
    produtos_faltantes: List[tuple[str, str]]


class DatabaseService:
    def __init__(self, db_config: Dict[str, Any], bot_config: Dict[str, Any]) -> None:
        self.db_config = db_config
        self.bot_config = bot_config
        self.view_name = bot_config.get(
            "view_pekc", "Rbdistrib_Trade.dbo.vw_ListaProdutosPecksKimberly"
        )
        if not self._is_safe_sql_identifier(self.view_name):
            raise ValueError("Nome da view inválido no config_bot.json")
        self.validation_query = bot_config.get("sql_validacao_vendedor", "").strip()

    def _connect(self) -> pyodbc.Connection:
        conn_str = (
            "DRIVER={ODBC Driver 17 for SQL Server};"
            f"SERVER={self.db_config['servidor']},{self.db_config.get('porta', 1433)};"
            f"DATABASE={self.db_config['database']};"
            f"UID={self.db_config['usuario']};"
            f"PWD={self.db_config['senha']};"
            f"Connection Timeout={self.db_config.get('timeout_conexao', 30)};"
            "TrustServerCertificate=yes;"
        )
        return pyodbc.connect(conn_str)

    def is_seller_validation_enabled(self) -> bool:
        return bool(self.validation_query)

    def is_seller_active(self, whatsapp_number: str) -> bool:
        if not self.validation_query:
            return True

        candidates = self._phone_candidates(whatsapp_number)
        with self._connect() as conn:
            cursor = conn.cursor()
            for phone in candidates:
                row = cursor.execute(self.validation_query, phone).fetchone()
                if row:
                    return True
        return False

    def get_client_pekc_status(self, cod_cliente: str) -> Optional[ClientPekcStatus]:
        if not re.fullmatch(r"\d{1,20}", cod_cliente):
            return None

        summary_sql = f"""
            WITH produtos AS (
                SELECT
                    COD_PRODUTO,
                    MAX(NOME_PRODUTO) AS NOME_PRODUTO,
                    MAX(ISNULL(QT_VENDIDA, 0)) AS QT_VENDIDA
                FROM {self.view_name}
                WHERE COD_CLIENTE = ?
                GROUP BY COD_PRODUTO
            )
            SELECT
                ? AS COD_CLIENTE,
                (
                    SELECT TOP 1 NOME_CLIENTE
                    FROM {self.view_name}
                    WHERE COD_CLIENTE = ?
                ) AS NOME_CLIENTE,
                SUM(CASE WHEN QT_VENDIDA > 0 THEN 1 ELSE 0 END) AS ITENS_POSITIVADOS,
                SUM(CASE WHEN QT_VENDIDA <= 0 THEN 1 ELSE 0 END) AS ITENS_FALTANTES
            FROM produtos;
        """

        missing_sql = f"""
            WITH produtos AS (
                SELECT
                    COD_PRODUTO,
                    MAX(NOME_PRODUTO) AS NOME_PRODUTO,
                    MAX(ISNULL(QT_VENDIDA, 0)) AS QT_VENDIDA
                FROM {self.view_name}
                WHERE COD_CLIENTE = ?
                GROUP BY COD_PRODUTO
            )
            SELECT
                CAST(COD_PRODUTO AS VARCHAR(50)) AS COD_PRODUTO,
                NOME_PRODUTO
            FROM produtos
            WHERE QT_VENDIDA <= 0
            ORDER BY NOME_PRODUTO, COD_PRODUTO;
        """

        with self._connect() as conn:
            cursor = conn.cursor()
            summary_row = cursor.execute(summary_sql, cod_cliente, cod_cliente, cod_cliente).fetchone()

            if not summary_row or summary_row.NOME_CLIENTE is None:
                return None

            missing_rows = cursor.execute(missing_sql, cod_cliente).fetchall()

        return ClientPekcStatus(
            cod_cliente=str(summary_row.COD_CLIENTE),
            nome_cliente=str(summary_row.NOME_CLIENTE),
            itens_positivados=int(summary_row.ITENS_POSITIVADOS or 0),
            itens_faltantes=int(summary_row.ITENS_FALTANTES or 0),
            produtos_faltantes=[(str(row.COD_PRODUTO), str(row.NOME_PRODUTO)) for row in missing_rows],
        )

    @staticmethod
    def _phone_candidates(raw_phone: str) -> List[str]:
        digits = "".join(ch for ch in raw_phone if ch.isdigit())
        candidates = [digits]
        if digits.startswith("55"):
            candidates.append(digits[2:])
        else:
            candidates.append(f"55{digits}")
        if len(digits) >= 11:
            candidates.append(digits[-11:])
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _is_safe_sql_identifier(identifier: str) -> bool:
        # Permite apenas nomes qualificados tipo db.schema.objeto (sem aspas/comandos).
        return bool(re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+){0,2}", identifier))
