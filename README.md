still getting this error: 



Error
Copy data1
Troubleshoot activity failures
 {
    "errorCode": "2200",
    "message": "Failure happened on 'Source' side. 'Type=Microsoft.Data.SqlClient.SqlException,Message=The replace function requires 3 argument(s).\r\nIncorrect syntax near ','.,Source=Framework Microsoft SqlClient Data Provider,'",
    "failureType": "UserError",
    "target": "Copy data1",
    "details": []
} 


on this code:


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



can we brainstorm on this? 


if the pipeline “Source query” box only accepts a single SELECT statement (no variable declarations, no CTE chains, no dynamic SQL execution), then the original multi‑statement script can’t run there. That’s why you’re getting the REPLACE error: the copy activity is trying to parse a long, multi‑part batch in a context that expects just one SELECT, and the nested formatting gets mangled (often a parenthesis or the opening REPLACE( is stripped, leaving a dangling , ',' , '_' pattern).

Here’s what you can do under that constraint:

1. Simplest: Drop the sanitizing logic from the query
Just pull the data and let the pipeline mapping handle renaming / illegal character replacement.

SELECT * FROM [tdfschema].[Key.Wrd4] WITH (NOLOCK);

Then:

In the Copy activity → Source tab: use that query.
In Sink / Mapping: manually change target column names (replace spaces, punctuation). Data Factory / Synapse mapping lets you assign different sink column names even if source ones are messy.
Pros: Zero SQL complexity.
Cons: Manual mapping effort (only once if you reuse dataset).

2. If you must cast problem data types (xml, variant, binary)
Do a manual, static SELECT listing columns you care about. Example pattern (you’d have to know or inspect column names once):

SELECT CAST([SomeMoneyCol] AS decimal(19,4)) AS [SomeMoneyCol_1], CAST([SomeDateCol] AS datetime2(3)) AS [SomeDateCol_2], CONVERT(nvarchar(36), [SomeGuid]) AS [SomeGuid_3], [PlainCol] AS [PlainCol_4] FROM [tdfschema].[Key.Wrd4] WITH (NOLOCK);

You’d only alias those that need casting; leave others direct.

How to discover columns if you can’t run metadata scripts:

Temporarily run: SELECT TOP 0 * FROM [tdfschema].[Key.Wrd4]; in a tool that lets you (SSMS, Azure portal query editor). If truly impossible, ask a DBA to give you the list once.
Or run a one-off pipeline with SELECT * and inspect the preview schema, then copy column names out.
3. Push sanitization upstream (preferred long term)
Ask a DBA (or whoever has database access) to create a view with sanitized aliases:

CREATE VIEW [tdfschema].[vw_KeyWrd4_Safe] AS SELECT CONVERT(nvarchar(4000), [SomeVariant]) AS SomeVariant_1, -- etc... * FROM [tdfschema].[Key.Wrd4];

Then your pipeline Source query is just:

SELECT * FROM [tdfschema].[vw_KeyWrd4_Safe];

No dynamic SQL needed.

4. Why you can’t safely auto-sanitize in the query field
All dynamic approaches rely on:

sys.columns or dm_exec_describe_first_result_set
Building a string of column expressions
Executing that string (EXEC / sp_executesql)
The copy activity’s “Source query” must be a final row-returning SELECT. It does not execute batches containing EXEC or variable assembly. Even a CTE block with multiple WITH elements plus variable assignments tends to fail in that environment or gets normalized (removing line starts), which breaks your nested REPLACE parentheses.

5. If you still want inline character replacement for just a few known bad column names
You can alias each manually:

SELECT [Col With Space] AS [Col_With_Space], [Col,Comma] AS [Col_Comma], [Col/Slash] AS [Col_Slash], [Col(Paren)] AS [Col_Paren], [NormalCol] AS [NormalCol] FROM [tdfschema].[Key.Wrd4] WITH (NOLOCK);

That’s fully valid in the query field—no REPLACE needed if you just hand-normalize.

6. Mapping vs. Query Tradeoff
Approach	Effort	Flexibility	Risk of Syntax Errors
SELECT * + Mapping	Low	High (rename anytime)	Very Low
Manual SELECT aliases	Medium (once)	Medium	Low
Upstream View	Medium (requires DBA)	High (reuse)	Very Low
Dynamic build (original)	High	High	High (not supported in field)
7. Recommended Path Now
Start with SELECT * and do the renames in mapping. If later you need type normalization for downstream tools (like forcing dates to datetime2(3)), evolve to a static SELECT or a view.

8. Quick checklist for you
Replace current multi-statement script with: SELECT * FROM [tdfschema].[Key.Wrd4] WITH (NOLOCK);
Open Mapping → sanitize column names (underscore invalid chars).
Test run.
Only if needed, iterate with explicit casts.
