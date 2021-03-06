'''
Created on 04/08/2010

@author: piranna
'''

from os      import listdir
from os.path import basename, join, splitext

from sqlparse import split2
from sqlparse.filters import Tokens2Unicode

from sql import Compact, GetColumns, GetLimit, IsType


def _transaction(func):
    def wrapper(self, *args, **kwargs):
        self.cursor.execute("BEGIN DEFERRED TRANSACTION")
        result = func(self, *args, **kwargs)
        self.connection.commit()
#        self.cursor.execute("END TRANSACTION")
        return result
    return wrapper


class AntiORM():
    '''
    classdocs
    '''
    def ParseDir(self, dirPath='sql'):
        "Build functions from the SQL queries inside the files at `dirPath`"

        for filename in listdir(dirPath):
            self.ParseFile(join(dirPath, filename), includePath=dirPath)

    def ParseFile(self, filePath, methodName=None, includePath='sql'):
        "Build a function from a file containing a SQL query"

        if not methodName:
            methodName = splitext(basename(filePath))[0]

        with open(filePath) as f:
            self.ParseString(f.read(), methodName, includePath)

    def ParseString(self, sql, methodName, includePath='sql'):
        "Build a function from a string containing a SQL query"

        stream = Compact(sql, includePath)

        # Insert statement (return last row id)
        if IsType('INSERT')(stream):
            self._statement_INSERT(stream, methodName)

        # One statement query
        elif len(split2(stream)) == 1:
            self._oneStatement(stream, methodName)

        # Multiple statement query
        else:
            self._multipleStatement(stream, methodName)

    def _statement_INSERT(self, stream, methodName):
        "Special case because we are interested in get inserted row id"
        stmts = split2(stream)

        # One statement query
        if len(stmts) == 1:
            def applyMethod(sql, methodName):
                @_transaction
                def method(self, **kwargs):
                    self.cursor.execute(sql, kwargs)
                    return self.cursor.lastrowid

                setattr(self.__class__, methodName, method)

            sql = unicode(stmts[0])

        # Multiple statement query (return last row id of first one)
        else:
            def applyMethod(stmts, methodName):
                @_transaction
                def method(self, _=None, **kwargs):
                    # Received un-named parameter, it would be a iterable
                    if _ != None:
                        # Parameters are given as a dictionary,
                        # put them in the correct place (bad guy...)
                        if isinstance(_, dict):
                            kwargs = _

                        # Iterable of parameters, execute as normal
                        else:
                            for kwargs in _:
                                for stmt in stmts:
                                    self.cursor.execute(stmt, kwargs)
                            return

                    self.cursor.execute(stmts[0], kwargs)
                    rowid = self.cursor.lastrowid

                    for stmt in stmts[1:]:
                        self.cursor.execute(stmt, kwargs)

                    return rowid

                setattr(self.__class__, methodName, method)

            sql = [unicode(x) for x in stmts]

        applyMethod(sql, methodName)

    def _oneStatement(self, stream, methodName):
        # One-value function
        if GetLimit(stream) == 1:
            self._oneStatement_value(stream, methodName)

        # Table function (several registers)
        else:
            self._oneStatement_table(stream, methodName)

    def _oneStatement_value(self, stream, methodName):
        columns = GetColumns(stream)

        def applyMethod(sql, methodName, column):
            # Value function (one register, one field)
            if len(columns) == 1 and columns[0] != '*':
                @_transaction
                def method(self, **kwargs):
                    result = self.cursor.execute(sql, kwargs)
                    result = result.fetchone()
                    if result:
                        return result[column]

            # Register function (one register, several fields)
            else:
                @_transaction
                def method(self, **kwargs):
                    result = self.cursor.execute(sql, kwargs)
                    return result.fetchone()

            setattr(self.__class__, methodName, method)

        applyMethod(Tokens2Unicode(stream), methodName, columns[0])

    def _oneStatement_table(self, stream, methodName):
        def applyMethod(sql, methodName):
            @_transaction
            def method(self, _=None, **kwargs):
                # Received un-named parameter, it would be a iterable
                if _ != None:
                    # Parameters are given as a dictionary,
                    # put them in the correct place (bad guy...)
                    if isinstance(_, dict):
                        kwargs = _

                    # Iterable of parameters, use executemany()
                    else:
                        return self.cursor.executemany(sql, _)

                # Execute single SQL statement
                result = self.cursor.execute(sql, kwargs)
                return result.fetchall()

            setattr(self.__class__, methodName, method)

        applyMethod(Tokens2Unicode(stream), methodName)

    def _multipleStatement(self, stream, methodName):
        def applyMethod(stmts, methodName):
            @_transaction
            def method(self, **kwargs):
                for stmt in stmts:
                    self.cursor.execute(stmt, kwargs)

            setattr(self.__class__, methodName, method)

        applyMethod([unicode(x) for x in split2(stream)], methodName)

    def __init__(self, db_conn, dirPath=None):
        '''
        Constructor
        '''
        self.connection = db_conn
        self.cursor = db_conn.cursor()

        if dirPath:
            self.ParseDir(dirPath)

    def __del__(self):
        self.connection.commit()
        self.connection.close()
