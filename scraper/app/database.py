import os
import boto3


class Database:
    def __init__(self):
        self.dynamodb = self.get_dynamodb_resource()
        self.table_name = "articles"
        self.articles_table = self.dynamodb.Table(self.table_name)

    def get_dynamodb_resource(self):
        """
        Creates a DynamoDB resource, connecting to either local or production.
        """
        if os.getenv("APP_ENV") == "development":
            return boto3.resource(
                "dynamodb",
                endpoint_url="http://localhost:8000",  # Or your configured local endpoint
                region_name="local",  # Region is required but can be arbitrary for local
                aws_access_key_id="dummyMyAccessKeyId",  # Required, but can be dummy for local
                aws_secret_access_key="dummySecretAccessKey",  # Required, but can be dummy for local
            )
        return boto3.resource("dynamodb")  # TODO: where to get aws prod credentials

    def put_item(self, item):
        """
        Puts an item into the DynamoDB table.
        """
        try:
            self.articles_table.put_item(
                Item=item,
            )
            print(f"Item added successfully: {item}")
        except Exception as e:
            print(f"Error adding item: {e}")


# class Article(SQLModel, table=True):
#     id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
#     created_at: datetime.datetime = Field(default_factory=datetime.datetime.now)
#     updated_at: datetime.datetime = Field(
#         sa_column=Column(DateTime(), onupdate=func.now())
#     )
#     url: str = Field(str, unique=True)
#     title: str
#     summary: str
#     content: str
#     author: str
#     num_comments: int | None = None
