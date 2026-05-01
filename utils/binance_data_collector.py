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
    
    def get_rate_by_date(self, target_date: str, has_time: bool = False) -> dict:
        """
        Возвращает исторический курс валюты. 
        Если has_time=True, ищет курсы, актуальные на конкретную минуту.
        Если has_time=False, берет последние данные за указанный день.
        """
        try:
            with self.db_connection:
                if has_time:
                    query_exact = """
                        SELECT DISTINCT ON (s.title, er.RateType) 
                            COALESCE(s.title, 'Unknown') as title, 
                            er.RateType, er.RateValue, er.Timestamp 
                        FROM ExchangeRates er
                        LEFT JOIN Sources s ON er.RateSource = s.SourceID
                        WHERE er.Timestamp::date = %s::date AND er.Timestamp <= %s::timestamp
                        ORDER BY s.title, er.RateType, er.Timestamp DESC;
                    """
                    self.db_cursor.execute(query_exact, (target_date, target_date))
                else:
                    query_exact = """
                        SELECT DISTINCT ON (s.title, er.RateType) 
                            COALESCE(s.title, 'Unknown') as title, 
                            er.RateType, er.RateValue, er.Timestamp 
                        FROM ExchangeRates er
                        LEFT JOIN Sources s ON er.RateSource = s.SourceID
                        WHERE er.Timestamp::date = %s::date
                        ORDER BY s.title, er.RateType, er.Timestamp DESC;
                    """
                    self.db_cursor.execute(query_exact, (target_date,))
                
                exact_matches = self.db_cursor.fetchall()
                
                if exact_matches:
                    return {"status": "exact", "data": exact_matches}

                # Поиск ближайших дат, если точного совпадения нет
                if has_time:
                    self.db_cursor.execute("SELECT Timestamp FROM ExchangeRates WHERE Timestamp < %s::timestamp ORDER BY Timestamp DESC LIMIT 1;", (target_date,))
                    before = self.db_cursor.fetchone()
                    self.db_cursor.execute("SELECT Timestamp FROM ExchangeRates WHERE Timestamp > %s::timestamp ORDER BY Timestamp ASC LIMIT 1;", (target_date,))
                    after = self.db_cursor.fetchone()
                else:
                    self.db_cursor.execute("SELECT DATE(Timestamp) FROM ExchangeRates WHERE Timestamp::date < %s::date ORDER BY Timestamp DESC LIMIT 1;", (target_date,))
                    before = self.db_cursor.fetchone()
                    self.db_cursor.execute("SELECT DATE(Timestamp) FROM ExchangeRates WHERE Timestamp::date > %s::date ORDER BY Timestamp ASC LIMIT 1;", (target_date,))
                    after = self.db_cursor.fetchone()

                return {
                    "status": "nearest",
                    "before_dt": before[0] if before else None,
                    "after_dt": after[0] if after else None,
                    "has_time": has_time
                }
        except psycopg2.Error as e:
            logger.error(f"RatesDataCollector Error: {e}")
            return None


