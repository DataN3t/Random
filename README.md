Yeah, that error is 100% about the query text, not the data inside the table. One of the REPLACE() chains is still malformed, so SQL Server is parsing a REPLACE( that doesn’t end up with 3 arguments.

Let’s kill the parenthesis hell and rewrite that safe_base expression cleanly and unambiguously.

Use this full script in your Synapse copy activity query (just paste it as-is):

DECLARE @schema sysname = N'tdfschema';
DECLARE @table  sysname = N'Key.Wrd4';

DECLARE @sql         nvarchar(max);
DECLARE @select_list nvarchar(max) = N'';

WITH cols_raw AS (
    SELECT c.column_id, col_name = c.name, typ_name = t.name
    FROM sys.columns c
    JOIN sys.types t ON c.user_type_id = t.user_type_id
    WHERE c.object_id = OBJECT_ID(QUOTENAME(@schema) + N'.' + QUOTENAME(@table))
),
cols_sanitized AS (
    SELECT
        column_id,
        col_name,
        typ_name,
        -- Replace disallowed characters (including parentheses) with _
        safe_base =
            REPLACE(
            REPLACE(
            REPLACE(
            REPLACE(
            REPLACE(
            REPLACE(
            REPLACE(
            REPLACE(
            REPLACE(
            REPLACE(
            REPLACE(
            REPLACE(
            REPLACE(
            REPLACE(
            REPLACE(
            REPLACE(
            REPLACE(
            REPLACE(
            REPLACE(
            REPLACE(col_name, ' ', '_')
                , ',', '_')
                , ';', '_')
                , '{', '_')
                , '}', '_')
                , '[', '_')
                , ']', '_')
                , '=', '_')
                , '.', '_')
                , '+', '_')
                , '-', '_')
                , '#', '_')
                , '"', '_')
                , '%', '_')
                , '/', '_')
                , '''', '_')
                , ':', '_')
                , '(', '_')
                , ')', '_')
),
cols_final AS (
    SELECT column_id, col_name, typ_name,
           base2 = CASE WHEN safe_base LIKE '[A-Za-z_]%' THEN safe_base ELSE N'c_' + safe_base END
    FROM cols_sanitized
),
cols AS (
    SELECT column_id, col_name, typ_name,
           safe_name = base2 + N'_' + CAST(column_id AS varchar(10))
    FROM cols_final
)
SELECT @select_list +=
    CASE
        WHEN @select_list = N'' THEN N'' ELSE N',' END + CHAR(13)+CHAR(10) +
    CASE
        WHEN typ_name = 'sql_variant'         THEN N'CONVERT(nvarchar(4000),' + QUOTENAME(col_name) + N') AS ' + QUOTENAME(safe_name)
        WHEN typ_name IN ('xml')              THEN N'CONVERT(nvarchar(max),'  + QUOTENAME(col_name) + N') AS ' + QUOTENAME(safe_name)
        WHEN typ_name IN ('uniqueidentifier') THEN N'CONVERT(nvarchar(36),'  + QUOTENAME(col_name) + N') AS ' + QUOTENAME(safe_name)
        WHEN typ_name IN ('hierarchyid','geography','geometry')
                                               THEN N'CONVERT(nvarchar(max),' + QUOTENAME(col_name) + N') AS ' + QUOTENAME(safe_name)
        WHEN typ_name IN ('money','smallmoney')
                                               THEN N'CAST(' + QUOTENAME(col_name) + N' AS decimal(19,4)) AS ' + QUOTENAME(safe_name)
        WHEN typ_name IN ('datetimeoffset')    THEN N'CAST(' + QUOTENAME(col_name) + N' AS datetime2(3)) AS ' + QUOTENAME(safe_name)
        WHEN typ_name IN ('datetime','smalldatetime','date','time','datetime2')
                                               THEN N'CAST(' + QUOTENAME(col_name) + N' AS datetime2(3)) AS ' + QUOTENAME(safe_name)
        WHEN typ_name IN ('image','varbinary','binary','rowversion','timestamp')
                                               THEN N'CAST(' + QUOTENAME(col_name) + N' AS varbinary(max)) AS ' + QUOTENAME(safe_name)
        ELSE QUOTENAME(col_name) + N' AS ' + QUOTENAME(safe_name)
    END
FROM cols
ORDER BY column_id;

SET @sql = N'SELECT ' + @select_list + CHAR(13)+CHAR(10) +
           N'FROM ' + QUOTENAME(@schema) + N'.' + QUOTENAME(@table) + N' WITH (NOLOCK);';

EXEC sys.sp_executesql @sql;

What changed / why this should fix it

The safe_base expression is now a strictly nested chain of REPLACE() calls:

Starts with REPLACE(col_name, ' ', '_')

Each subsequent REPLACE wraps the previous result and adds exactly 2 more arguments.

No trailing commas, and the number of REPLACE( calls exactly matches the number of closing ).

So the "The replace function requires 3 argument(s)" and "Incorrect syntax near ','" errors are purely about that expression, not about bad characters inside your data. This version should compile cleanly and let Synapse happily read from SQL and write Parquet.

If it still throws something, send me the new error message and we’ll squash the next one.
