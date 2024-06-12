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


