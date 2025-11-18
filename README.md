Yeah, this is still the query text, not the data. That REPLACE chain is brittle as hell, and your current version actually does have an unbalanced set of parentheses (I counted them programmatically to be sure).

Let’s stop fighting that and switch to a much cleaner approach: TRANSLATE.

TRANSLATE lets you replace a whole set of single characters in one go, no 20× nested REPLACE() calls, no parenthesis misery.

New version using TRANSLATE

Paste this whole script into the Synapse “Source query” box:

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
        -- Replace disallowed characters (space, punctuation, parentheses) with _
        safe_base = TRANSLATE(
            col_name,
            ' ,;{}[]=.#+"/%'':()-',
            '___________________'
        )
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

What this does / why it fixes your error

TRANSLATE(col_name, ' ,;{}[]=.#+"/%'':()-', '___________________')

First string = all characters you don’t like:
space, ,, ;, {, }, [, ], =, ., +, -, #, ", /, %, ', :, (, ).
(19 characters total)

Second string = 19 underscores.

Result: every one of those characters becomes _ in one shot.

No nested REPLACE chain → no way for SQL Server to complain “REPLACE requires 3 arguments” because we’re not using it anymore.

Everything else in your script (type casting, dynamic select list, NOLOCK) stays exactly as you had it.

If you get a new error

If it says something like “TRANSLATE is not a recognized built-in function name” then we know your SQL compatibility level is too old / Synapse flavor doesn’t support TRANSLATE. In that case we’ll go to Plan B: either:

simplify to SELECT * and do renaming in mapping, or

use a much smaller, correctly-balanced REPLACE chain only for the 2–3 characters that actually occur in your columns.

But first: try this TRANSLATE version and send me the new error (or a success message 😄).
