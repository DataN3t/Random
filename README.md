almost! getting this error now: 



Error
Copy data1
Troubleshoot activity failures
 {
    "errorCode": "2200",
    "message": "Failure happened on 'Source' side. 'Type=Microsoft.Data.SqlClient.SqlException,Message=Must declare the scalar variable \"@schema\".\r\nMust declare the scalar variable \"@schema\".\r\nMust declare the scalar variable \"@schema\".,Source=Framework Microsoft SqlClient Data Provider,'",
    "failureType": "UserError",
    "target": "Copy data1",
    "details": []
} 




tdfschema.Key.Wrd4


SQLDECLARE @schema sysname = N'tdfschema'
DECLARE @table  sysname = N'Key.Wrd4'

DECLARE @sql    nvarchar(max) = N'';
DECLARE @columns nvarchar(max) = N'';

-- Build the column list – every column as string + safe Parquet name
SELECT @columns += N',' + CHAR(10) + 
       N'    CONVERT(nvarchar(max), ' + QUOTENAME(name) + N') AS ' +
       -- This is the magic: replace only ( and ) with _  → kills the "(StatementDate)" parser bug
       QUOTENAME(
           REPLACE(
               REPLACE(name, '(', '_'),
               ')', '_'
           )
       )
FROM sys.columns
WHERE object_id = OBJECT_ID(QUOTENAME(@schema) + N'.' + QUOTENAME(@table))
ORDER BY column_id;

SET @columns = STUFF(@columns, 1, 5, N'');

SET @sql = N'SELECT ' + CHAR(10) + @columns + CHAR(10) +
           N'FROM ' + QUOTENAME(@schema) + N'.' + QUOTENAME(@table) + N' WITH (NOLOCK);';

EXEC sp_executesql @sql;




almost there. not quite working yet 
