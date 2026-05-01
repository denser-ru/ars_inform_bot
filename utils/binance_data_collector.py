import requests
import psycopg2
import argparse, sys
from datetime import datetime

class RatesDataCollector:
    def __init__(self, config, dbname="exchange_rates"):
        self.config = config
        self.config["dbname"] = dbname
        self.db_connection = psycopg2.connect(**config)
        self.db_cursor = self.db_connection.cursor()

    def get_sourses(self, limit=10):
        # Получение данных из БД по последней дате или по переданной дате
        self.db_cursor.execute("SELECT SourceName, SourceID, title FROM Sources LIMIT %s;", (limit,))
        return self.db_cursor.fetchall()

    def get_data(self, source_id, tradeType, date=None, limit=10):
        # Получение данных из БД по последней дате или по переданной дате
        if date is None:
            self.db_cursor.execute(
                "SELECT * FROM ExchangeRates WHERE RateSource = %s AND RateType = %s ORDER BY Timestamp DESC LIMIT 1;",
                ( source_id, tradeType, )
            )
        else:
            self.db_cursor.execute(
                "SELECT * FROM ExchangeRates WHERE RateSource = %s AND RateType = %s AND Timestamp = %s LIMIT %s;",
                ( source_id, tradeType, date, limit, )
            )
        return self.db_cursor.fetchall()
    
    def get_rate_by_date(self, target_date: str) -> dict:
        try:
            # Используем ::date для надежного каста строки в дату
            self.db_cursor.execute(
                """
                SELECT DISTINCT ON (s.title, er.RateType) 
                    COALESCE(s.title, 'Unknown') as title, 
                    er.RateType, er.RateValue, er.Timestamp 
                FROM ExchangeRates er
                LEFT JOIN Sources s ON er.RateSource = s.SourceID
                WHERE DATE(er.Timestamp) = %s::date
                ORDER BY s.title, er.RateType, er.Timestamp DESC;
                """,
                (target_date,)
            )
            exact_matches = self.db_cursor.fetchall()
            
            if exact_matches:
                return {"status": "exact", "data": exact_matches}

            # Ищем границы, если точной даты нет
            self.db_cursor.execute(
                "SELECT DATE(Timestamp) FROM ExchangeRates WHERE DATE(Timestamp) < %s::date ORDER BY Timestamp DESC LIMIT 1;",
                (target_date,)
            )
            before = self.db_cursor.fetchone()

            self.db_cursor.execute(
                "SELECT DATE(Timestamp) FROM ExchangeRates WHERE DATE(Timestamp) > %s::date ORDER BY Timestamp ASC LIMIT 1;",
                (target_date,)
            )
            after = self.db_cursor.fetchone()

            return {
                "status": "nearest",
                "before_date": before[0] if before else None,
                "after_date": after[0] if after else None
            }
        except psycopg2.Error as e:
            print(f"RatesDataCollector Error: {e}")
            return None


