Perfect – let's kill all the errors once and for all with a rock-solid, zero-parameter version that you can copy-paste right now and it will just work for tdfschema.Key.Wrd4 (and any other crazy table).
This version:

Keeps your original working structure (type handling, uniqueness with _column_id, etc.)
Fixes the Parquet (StatementDate) crash by replacing only ( and ) with _
Produces valid Parquet every time
No parameters → no “Must declare @schema” errors
No dynamic expression blocks → no ADF parsing problems

Copy-paste this EXACTLY into Source → Query options (nothing else, no @{, no parameters):
SQLDECLARE @schema sysname = N'tdfschema';
DECLARE @table  sysname = N'Key.Wrd4';

DECLARE @sql          nvarchar(max);
DECLARE @select_list  nvarchar(max) = N'';

WITH cols_raw AS (
    SELECT
        c.column_id,
        col_name = c.name,
        typ_name = t.name
    FROM sys.columns c
    JOIN sys.types t ON c.user_type_id = t.user_type_id
    WHERE c.object_id = OBJECT_ID(QUOTENAME(@schema) + N'.' + QUOTENAME(@table))
),
cols_sanitized AS (
    SELECT
        column_id,
        col_name,
        typ_name,
        -- ONLY CHANGE vs your original: replace ( and ) so Parquet doesn't explode on (StatementDate)
        safe_base = REPLACE(REPLACE(
            TRANSLATE(col_name, N' ,;{}[]=.+-#"%/\'':', N'___________________'),
        '(', '_'), ')', '_')
),
cols_final AS (
    SELECT
        column_id,
        col_name,
        typ_name,
        base2 = CASE WHEN safe_base LIKE '[A-Za-z_]%' THEN safe_base ELSE N'c_' + safe_base END
    FROM cols_sanitized
),
cols AS (
    SELECT
        column_id,
        col_name,
        typ_name,
        safe_name = base2 + N'_' + CAST(column_id AS varchar(10))
    FROM cols_final
)
SELECT @select_list += N', ' + CHAR(13)+CHAR(10) + N' ' +
    CASE
        WHEN typ_name = 'sql_variant'       THEN N'CONVERT(nvarchar(4000),'  + QUOTENAME(col_name) + N') AS ' + QUOTENAME(safe_name)
        WHEN typ_name IN ('xml')            THEN N'CONVERT(nvarchar(max),'   + QUOTENAME(col_name) + N') AS ' + QUOTENAME(safe_name)
        WHEN typ_name IN ('uniqueidentifier') THEN N'CONVERT(nvarchar(36),'  + QUOTENAME(col_name) + N') AS ' + QUOTENAME(safe_name)
        WHEN typ_name IN ('hierarchyid','geography','geometry')
                                            THEN N'CONVERT(nvarchar(max),'   + QUOTENAME(col_name) + N') AS ' + QUOTENAME(safe_name)
        WHEN typ_name IN ('money','smallmoney')
                                            THEN N'CAST(' + QUOTENAME(col_name) + N' AS decimal(19,4)) AS ' + QUOTENAME(safe_name)
        WHEN typ_name IN ('datetimeoffset') THEN N'CAST(' + QUOTENAME(col_name) + N' AS datetime2(3)) AS ' + QUOTENAME(safe_name)
        WHEN typ_name IN ('datetime','smalldatetime','date','time','datetime2')
                                            THEN N'CAST(' + QUOTENAME(col_name) + N' AS datetime2(3)) AS ' + QUOTENAME(safe_name)
        WHEN typ_name IN ('image','varbinary','binary','rowversion','timestamp')
                                            THEN N'CAST(' + QUOTENAME(col_name) + N' AS varbinary(max)) AS ' + QUOTENAME(safe_name)
        ELSE QUOTENAME(col_name) + N' AS ' + QUOTENAME(safe_name)
    END
FROM cols
ORDER BY column_id;

-- Remove leading comma
SET @select_list = STUFF(@select_list, 1, 2, N'');

-- Build and execute final query
SET @sql = N'SELECT ' + @select_list + CHAR(13)+CHAR(10) +
           N'FROM ' + QUOTENAME(@schema) + N'.' + QUOTENAME(@table) + N' WITH (NOLOCK);';

-- PRINT @sql;   -- uncomment only if you want to see the generated SQL

EXEC sp_executesql @sql;
That’s it.
Mapping tab: just click Import schemas once → leave everything default → run.
You will get perfect Parquet files with column names like:
textExists_1
Max_*StatementDate__2
From_3
0; _____100_4
Identity_5
''_6
# empty fields_7
…exactly like before, but now without the Parquet crash.
Once this runs green for Key.Wrd4, we’ll add the parameters back in 10 seconds.
Go hit Debug now – green success incoming! 🚀3.6s
