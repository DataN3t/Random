getting this error now: 


Error
Copy data1
Troubleshoot activity failures
 {
    "errorCode": "2200",
    "message": "Failure happened on 'Source' side. ErrorCode=SqlInvalidDbQueryString,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The specified SQL Query is not valid. It could be caused by that the query doesn't return any data. Invalid query: '-- ADF dynamic expression block – protects @ variables\ndeclare @schema sysname = N'@pipeline().parameters.TableSchema';\ndeclare @table  sysname = N'@pipeline().parameters.TableName';\n\ndeclare @sql    nvarchar(max) = N'';\ndeclare @columns nvarchar(max) = N'';\n\n-- Build column list safely (handles / * ( ) ; # + ? % - : and everything else)\nselect @columns = @columns + N',' + char(10) + N'    CONVERT(nvarchar(max), ' \n                + quotename(name) + N') AS ' \n                + quotename(replace(replace(name,'(','_'),')','_'), '\"')  -- only ( and ) → _ , quoted with \"\nfrom sys.columns \nwhere object_id = object_id(quotename(@schema) + N'.' + quotename(@table))\norder by column_id;\n\n-- Remove leading comma\nset @columns = stuff(@columns, 1, 6, N'');\n\n-- Final query\nset @sql = N'SELECT' + char(10) + @columns + char(10) +\n           N'FROM ' + quotename(@schema) + N'.' + quotename(@table) + N' WITH (NOLOCK);';\n\n-- For debugging only (remove // before PRINT when testing)\n-- print @sql;\n\nexec sp_executesql @sql;',Source=Microsoft.DataTransfer.Connectors.MSSQL,'",
    "failureType": "UserError",
    "target": "Copy data1",
    "details": []
} 


mind you, this was the first query that i used: 

DECLARE @schema sysname = N'tdfschema';
DECLARE @table  sysname = N'Key-Wrd-5';

DECLARE @sql          nvarchar(max);
DECLARE @select_list  nvarchar(max);

/* Build metadata with safe aliases */
WITH cols_raw AS (
    SELECT 
        c.column_id,
        col_name = c.name,
        typ_name = t.name
    FROM sys.columns c
    JOIN sys.types  t ON c.user_type_id = t.user_type_id
    WHERE c.object_id = OBJECT_ID(QUOTENAME(@schema) + N'.' + QUOTENAME(@table))
),
-- sanitize names: replace disallowed chars with underscores; also replace dot
-- TRANSLATE requires SQL Server 2017+; if older, we can switch to nested REPLACE (ask me).
cols_sanitized AS (
    SELECT
        column_id,
        col_name,
        typ_name,
        -- replace spaces, commas, semicolons, braces, parentheses, equals, brackets, dots, plus/minus, hash, quotes
        safe_base0 = TRANSLATE(col_name, N' ,;{}()[]=.+-#"%/\'':', N'____________________'),
        -- collapse doubles like "<=" or ">=" etc. (optional)
        safe_base  = REPLACE(REPLACE(REPLACE(REPLACE(TRANSLATE(col_name, N' ,;{}()[]=.+-#"%/''::', N'____________________'), '<', '_'), '>', '_'), '&', '_'), '@', '_')
    FROM cols_raw
),
cols_final AS (
    SELECT
        column_id,
        col_name,
        typ_name,
        -- ensure it starts with letter or underscore; if not, prefix "c_"
        base2 = CASE WHEN safe_base LIKE '[A-Za-z_]%' THEN safe_base ELSE 'c_' + safe_base END
    FROM cols_sanitized
),
cols AS (
    -- guarantee uniqueness by suffixing column_id
    SELECT
        column_id,
        col_name,
        typ_name,
        safe_name = base2 + '_' + CAST(column_id AS varchar(10))
    FROM cols_final
)

/* Build the SELECT list in column_id order using XML concat (works on all versions) */
SELECT @select_list =
    STUFF((
        SELECT
            ', ' + CHAR(13) + CHAR(10) +
            '  ' +
            CASE
                WHEN typ_name = 'sql_variant'
                    THEN 'CONVERT(nvarchar(4000),' + QUOTENAME(col_name) + ') AS ' + QUOTENAME(safe_name)
                WHEN typ_name IN ('xml')
                    THEN 'CONVERT(nvarchar(max),' + QUOTENAME(col_name) + ') AS ' + QUOTENAME(safe_name)
                WHEN typ_name IN ('uniqueidentifier')
                    THEN 'CONVERT(nvarchar(36),' + QUOTENAME(col_name) + ') AS ' + QUOTENAME(safe_name)
                WHEN typ_name IN ('hierarchyid','geography','geometry')
                    THEN 'CONVERT(nvarchar(max),' + QUOTENAME(col_name) + ') AS ' + QUOTENAME(safe_name)
                WHEN typ_name IN ('money','smallmoney')
                    THEN 'CAST(' + QUOTENAME(col_name) + ' AS decimal(19,4)) AS ' + QUOTENAME(safe_name)
                WHEN typ_name IN ('datetimeoffset')
                    THEN 'CAST(' + QUOTENAME(col_name) + ' AS datetime2(3)) AS ' + QUOTENAME(safe_name)
                WHEN typ_name IN ('datetime','smalldatetime','date','time','datetime2')
                    THEN 'CAST(' + QUOTENAME(col_name) + ' AS datetime2(3)) AS ' + QUOTENAME(safe_name)
                WHEN typ_name IN ('image','varbinary','binary','rowversion','timestamp')
                    THEN 'CAST(' + QUOTENAME(col_name) + ' AS varbinary(max)) AS ' + QUOTENAME(safe_name)
                ELSE QUOTENAME(col_name) + ' AS ' + QUOTENAME(safe_name)
            END
        FROM cols
        ORDER BY column_id
        FOR XML PATH(''), TYPE
    ).value('.', 'nvarchar(max)'), 1, 2, '');  -- trim the initial ", "

/* Final SELECT */
SET @sql = N'SELECT ' + @select_list + N'
FROM ' + QUOTENAME(@schema) + N'.' + QUOTENAME(@table) + N' WITH (NOLOCK);';

EXEC sys.sp_executesql @sql;



and for the most part it worked. i think we should keep somewhat of this structure becasue the data inside was wrong, but it did came through as parquet 
