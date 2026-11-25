"""版本化迁移脚本包（自研轻量机制，配合 app/db/migration.py 使用）。

脚本文件命名规范：vNNN_<名称>.py（NNN 为三位零填充版本号）。
每个脚本必须定义 VERSION: int 与 upgrade(conn) 函数（conn 为 sqlite3 原生连接，
在同一个事务内执行 DDL，成功后由框架写入 tb_schema_migration）。

升级脚本只增不改（WBS 风险表：新版本 = 新脚本）。
"""
