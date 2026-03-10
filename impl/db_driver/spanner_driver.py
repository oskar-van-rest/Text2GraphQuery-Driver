from google.cloud import spanner
from driver.evaluation import DatabaseDriver

class SpannerAdapter(DatabaseDriver):
    """
    Google Cloud Spanner Adapter for Text-to-GQL Evaluation
    """
    def __init__(self, project_id, instance_id, database_id):
        self.project_id = project_id
        self.instance_id = instance_id
        self.database_id = database_id
        self.database = None

    def connect(self):
        try:
            spanner_client = spanner.Client(project=self.project_id)
            instance = spanner_client.instance(self.instance_id)
            self.database = instance.database(self.database_id)
       
            with self.database.snapshot() as snapshot:
                snapshot.execute_sql("SELECT 1")
            print(f"Connected to Spanner: {self.database_id}")
        except Exception as e:
            print(f"Failed to connect to Spanner: {e}")
            self.database = None

    def query(self, gql: str, db_name: str = None) -> list:
        if not self.database:
            return None
        try:
            with self.database.snapshot() as snapshot:
                return list(snapshot.execute_sql(gql, timeout=120.0))
        except Exception:
            return None

    def close(self):
        pass