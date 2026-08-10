from .query_executor import QueryExecutionPolicy, QueryExecutor
from .query_service import QueryService
from .query_store import QueryStore
from .tencentcloud import TencentCloudClient


def build_query_service(asset_store):
    policy = QueryExecutionPolicy.from_env()
    query_store = QueryStore(asset_store.conn)
    query_store.init_schema()
    if not policy.enabled:
        return None
    executor = QueryExecutor(TencentCloudClient.dlc_from_env(), policy)
    return QueryService(query_store, asset_store, executor, policy)
