# coding=utf-8
"""Wind 金融工程数据库"""
import re
import os
import datetime as dt

import numpy as np
import pandas as pd
from traits.api import Enum, Int, Str, Range, Password, Bool

from QuantStudio.Tools.SQLDBFun import genSQLInCondition
from QuantStudio.Tools.FileFun import readJSONFile
from QuantStudio.Tools.DataTypeFun import readNestedDictFromHDF5, writeNestedDict2HDF5
from QuantStudio.Tools.DateTimeFun import getDateSeries, getDateTimeSeries
from QuantStudio import __QS_Error__, __QS_MainPath__, __QS_LibPath__
from QuantStudio.FactorDataBase.FactorDB import FactorDB, FactorTable, _adjustDateTime

class _DBTable(FactorTable):
    def getMetaData(self, key=None):
        TableInfo = self._FactorDB._TableInfo.ix[self.Name]
        if key is None:
            return TableInfo
        else:
            return TableInfo.get(key, None)
    @property
    def FactorNames(self):
        FactorInfo = self._FactorDB._FactorInfo.ix[self.Name]
        return FactorInfo[FactorInfo["FieldType"]=="因子"].index.tolist()
    def getFactorMetaData(self, factor_names=None, key=None):
        if factor_names is None:
            factor_names = self.FactorNames
        FactorInfo = self._FactorDB._FactorInfo.ix[self.Name]
        if key=="DataType":
            if hasattr(self, "_DataType"): return self._DataType.ix[factor_names]
            MetaData = FactorInfo["DataType"].ix[factor_names]
            for i in range(MetaData.shape[0]):
                iDataType = MetaData.iloc[i].lower()
                if iDataType.find("number")!=-1: MetaData.iloc[i] = "double"
                else: MetaData.iloc[i] = "string"
            return MetaData
        elif key=="Description": return FactorInfo["Description"].ix[factor_names]
        elif key is None:
            return pd.DataFrame({"DataType":self.getFactorMetaData(factor_names, key="DataType"),
                                 "Description":self.getFactorMetaData(factor_names, key="Description")})
        else:
            return pd.Series([None]*len(factor_names), index=factor_names, dtype=np.dtype("O"))

class _MarketTable(_DBTable):
    """行情因子表"""
    FillNa = Bool(True, arg_type="Bool", label="缺失填充", order=0)
    LookBack = Int(0, arg_type="Integer", label="回溯天数", order=1)
    def getID(self, ifactor_name=None, idt=None, args={}):
        DBTableName = self.FactorDB.TablePrefix+self.FactorDB.TableName2DBTableName([self.Name])[self.Name]
        IDTable = self.FactorDB.TablePrefix+"tb_object_0001"
        FieldDict = self.FactorDB.FieldName2DBFieldName(table=self.Name, fields=["日期",'证券ID'])
        SQLStr = "SELECT DISTINCT "+IDTable+".f1_0001 "# ID
        SQLStr += "FROM "+IDTable+", "+DBTableName+" "
        SQLStr += 'WHERE '+IDTable+".F16_0001="+DBTableName+"."+FieldDict['证券ID']+" "
        if idt is not None:
            SQLStr += "WHERE "+DBTableName+"."+FieldDict["日期"]+"='"+idt.strftime("%Y%m%d")+"' "
        SQLStr += "ORDER BY "+IDTable+".f1_0001"
        return [iRslt[0] for iRslt in self.FactorDB.fetchall(SQLStr)]
    def getDateTime(self, ifactor_name=None, iid=None, start_dt=None, end_dt=None, args={}):
        DBTableName = self.FactorDB.TablePrefix+self.FactorDB.TableName2DBTableName([self.Name])[self.Name]
        FieldDict = self.FactorDB.FieldName2DBFieldName(table=self.Name, fields=["日期", "证券ID"])
        SQLStr = "SELECT DISTINCT "+DBTableName+"."+FieldDict["日期"]+" "# 日期
        SQLStr += "FROM "+DBTableName+" "
        if iid is not None:
            iEquityID = self.FactorDB.ID2EquityID([iid])[iid]
            SQLStr += "WHERE "+DBTableName+"."+FieldDict["证券ID"]+"='"+iEquityID+"' "
        else:
            SQLStr += "WHERE "+DBTableName+"."+FieldDict["证券ID"]+" IS NOT NULL "
        if start_dt is not None:
            SQLStr += "AND "+DBTableName+"."+FieldDict["日期"]+">='"+start_dt.strftime("%Y%m%d")+"' "
        if end_dt is not None:
            SQLStr += "AND "+DBTableName+"."+FieldDict["日期"]+"<='"+end_dt.strftime("%Y%m%d")+"' "
        SQLStr += "ORDER BY "+DBTableName+"."+FieldDict["日期"]
        return list(map(lambda x: dt.datetime(int(x[0][:4]), int(x[0][4:6]), int(x[0][6:8]), 23, 59, 59, 999999), self.FactorDB.fetchall(SQLStr)))
     # 时间点默认是当天, ID 默认是 [000001.SH], 特别参数: 回溯天数
    def _getRawData(self, fields, ids=None, start_date=None, end_date=None, args={}):
        DBTableName = self.FactorDB.TablePrefix+self.FactorDB.TableName2DBTableName([self.Name])[self.Name]
        IDTable = self.FactorDB.TablePrefix+"tb_object_0001"
        FieldDict = self.FactorDB.FieldName2DBFieldName(table=self.Name,fields=["日期",'证券ID']+fields)
        # 日期, ID, 因子数据
        SQLStr = 'SELECT '+DBTableName+'.'+FieldDict["日期"]+', '# 日期
        SQLStr += IDTable+".f1_0001, "# ID
        for iField in fields:
            SQLStr += DBTableName+'.'+FieldDict[iField]+', '# 因子数据
        SQLStr = SQLStr[:-2]+' '
        SQLStr += 'FROM '+IDTable+", "+DBTableName+' '
        SQLStr += 'WHERE '+IDTable+".F16_0001="+DBTableName+'.'+FieldDict['证券ID']+' '
        if ids is not None:
            SQLStr += 'AND ('+genSQLInCondition(IDTable+".f1_0001", ids, is_str=True, max_num=1000)+") "
        if start_date is not None:
            SQLStr += 'AND '+DBTableName+'.'+FieldDict["日期"]+'>=\''+start_date.strftime("%Y%m%d")+'\' '
        if end_date is not None:
            SQLStr += 'AND '+DBTableName+'.'+FieldDict["日期"]+'<=\''+end_date.strftime("%Y%m%d")+'\' '
        SQLStr += 'ORDER BY '+IDTable+'.f1_0001, '+DBTableName+'.'+FieldDict["日期"]
        RawData = self.FactorDB.fetchall(SQLStr)
        if RawData==[]:
            RawData = pd.DataFrame(columns=['日期','ID']+fields)
        else:
            RawData = pd.DataFrame(np.array(RawData), columns=['日期','ID']+fields)
        return RawData
    def __QS_readData__(self, factor_names=None, ids=None, dts=None, args={}):
        if dts: StartDate, EndDate = dts[0].date(), dts[-1].date()
        else: StartDate, EndDate = None, None
        FillNa = args.get("缺失填充", self.FillNa)
        if FillNa: StartDate -= dt.timedelta(args.get("回溯天数", self.LookBack))
        if factor_names is None: factor_names = self.FactorNames
        RawData = self._getRawData(factor_names, ids, StartDate, EndDate, args=args)
        RawData = RawData.set_index(["日期", "ID"])
        DataType = self.getFactorMetaData(factor_names=factor_names, key="DataType")
        Data = {}
        for iFactorName in RawData.columns:
            iRawData = RawData[iFactorName].unstack()
            if DataType[iFactorName]=="double":
                iRawData = iRawData.astype("float")
            Data[iFactorName] = iRawData
        Data = pd.Panel(Data).loc[factor_names]
        Data.major_axis = [dt.datetime(int(iDate[:4]), int(iDate[4:6]), int(iDate[6:8]), 23, 59, 59, 999999) for iDate in Data.major_axis]
        Data = _adjustDateTime(Data, dts, fillna=FillNa, method="pad")
        if ids is not None: Data = Data.ix[:, :, ids]
        return Data

class _ConstituentTable(_DBTable):
    """成份因子表"""
    @property
    def FactorNames(self):
        if not hasattr(self, "_IndexIDs"):# DataFrame(证券ID, index=[指数ID])
            DBTableName = self.FactorDB.TablePrefix+self.FactorDB.TableName2DBTableName([self.Name])[self.Name]
            IDTable = self.FactorDB.TablePrefix+"tb_object_0001"
            FieldDict = self.FactorDB.FieldName2DBFieldName(table=self.Name, fields=["指数ID"])
            SQLStr = "SELECT DISTINCT "+IDTable+".f1_0001, "# 指数 ID
            SQLStr += DBTableName+"."+FieldDict['指数ID']+" "# 指数证券 ID
            SQLStr += 'FROM '+DBTableName+', '+IDTable+" "
            SQLStr += 'WHERE '+DBTableName+'.'+FieldDict['指数ID']+'='+IDTable+'.f16_0001 '
            SQLStr += "ORDER BY "+IDTable+".f1_0001"
            self._IndexIDs = pd.DataFrame(np.array(self.FactorDB.fetchall(SQLStr)), columns=["指数 ID", "指数证券 ID"])
            self._IndexIDs.set_index(["指数 ID"], inplace=True)
        return self._IndexIDs.index.tolist()
    # 返回指数为 ifactor_name 在给定时点 idt 的所有成份股
    # 如果 idt 为 None, 将返回指数 ifactor_name 的所有历史成份股
    # 如果 ifactor_name 为 None, 将返回表里所有成份股 ID
    def getID(self, ifactor_name=None, idt=None, args={}):
        DBTableName = self.FactorDB.TablePrefix+self.FactorDB.TableName2DBTableName([self.Name])[self.Name]
        IDTable = self.FactorDB.TablePrefix+"tb_object_0001"
        FieldDict = self.FactorDB.FieldName2DBFieldName(table=self.Name, fields=['证券ID','指数ID','纳入日期','剔除日期','最新标志'])
        SQLStr = "SELECT DISTINCT "+IDTable+".f1_0001 "# ID
        SQLStr += "FROM "+IDTable+", "+DBTableName+" "
        SQLStr += 'WHERE '+IDTable+'.F16_0001='+DBTableName+'.'+FieldDict['证券ID']+' '
        if ifactor_name is not None:
            IndexEquityID = self.FactorDB.ID2EquityID([ifactor_name])[ifactor_name]
            SQLStr += 'AND '+DBTableName+'.'+FieldDict['指数ID']+'=\''+IndexEquityID+'\' '
        if idt is not None:
            SQLStr += "AND "+DBTableName+"."+FieldDict["纳入日期"]+"<='"+idt.strftime("%Y%m%d")+"' "
            SQLStr += "AND (("+DBTableName+"."+FieldDict["剔除日期"]+">'"+idt.strftime("%Y%m%d")+"') "
            SQLStr += "OR ("+DBTableName+"."+FieldDict["最新标志"]+"=1)) "
        SQLStr += "ORDER BY "+IDTable+".f1_0001"
        return [iRslt[0] for iRslt in self.FactorDB.fetchall(SQLStr)]
    def getDateTime(self, ifactor_name=None, iid=None, start_dt=None, end_dt=None, args={}):
        DBTableName = self.FactorDB.TablePrefix+self.FactorDB.TableName2DBTableName([self.Name])[self.Name]
        FieldDict = self.FactorDB.FieldName2DBFieldName(table=self.Name, fields=['证券ID','指数ID','纳入日期','剔除日期','最新标志'])
        SQLStr = "SELECT "+DBTableName+"."+FieldDict["纳入日期"]+" "# 纳入日期
        SQLStr += DBTableName+"."+FieldDict["剔除日期"]+" "# 剔除日期
        SQLStr += "FROM "+DBTableName+" "
        SQLStr += "WHERE "+DBTableName+"."+FieldDict["纳入日期"]+" IS NOT NULL "
        if ifactor_name is not None:
            IndexEquityID = self.FactorDB.ID2EquityID([ifactor_name])[ifactor_name]
            SQLStr += 'AND '+DBTableName+'.'+FieldDict['指数ID']+'=\''+IndexEquityID+'\' '
        if iid is not None:
            iEquityID = self.FactorDB.ID2EquityID([iid])[iid]
            SQLStr += "AND "+DBTableName+"."+FieldDict["证券ID"]+"='"+iEquityID+"' "
        if start_dt is not None:
            SQLStr += "AND (("+DBTableName+"."+FieldDict["剔除日期"]+">'"+start_dt.strftime("%Y%m%d")+"') "
            SQLStr += "OR ("+DBTableName+"."+FieldDict["剔除日期"]+" IS NULL))"
        if end_dt is not None:
            SQLStr += "AND "+DBTableName+"."+FieldDict["纳入日期"]+"<='"+end_dt.strftime("%Y%m%d")+"' "
        SQLStr += "ORDER BY "+DBTableName+"."+FieldDict["纳入日期"]
        Data = self.FactorDB.fetchall(SQLStr)
        TimeDelta = dt.timedelta(seconds=59, microseconds=999999, minutes=59, hours=23)
        DateTimes = set()
        for iStartDate, iEndDate in Data:
            iStartDT = dt.datetime.strptime(iStartDate, "%Y%m%d") + TimeDelta
            if iEndDate is None: iEndDT = (dt.datetime.now() if end_dt is None else end_dt)
                
            DateTimes = DateTimes.union(set(getDateTimeSeries(start_dt=iStartDT, end_dt=iEndDT, timedelta=dt.timedelta(1))))
        return sorted(DateTimes)
    def __QS_readData__(self, factor_names=None, ids=None, dts=None, args={}):
        if dts: StartDate, EndDate = dts[0].date(), dts[-1].date()
        else: StartDate, EndDate = None, None
        if factor_names is None: factor_names = self.FactorNames
        RawData = self._getRawData(factor_names, ids, start_date=StartDate, end_date=EndDate, args=args)
        if StartDate is None:
            StartDate = dt.datetime.strptime(np.min(RawData["纳入日期"].values), "%Y%m%d").date()
            DateSeries = getDateSeries(StartDate, dt.date.today())
        else:
            DateSeries = getDateSeries(dts[0].date(), dts[-1].date())
        Data = {}
        for iIndexID in factor_names:
            iRawData = RawData[RawData["指数ID"]==iIndexID].set_index(["ID"])
            iData = pd.DataFrame(0, index=DateSeries, columns=pd.unique(iRawData.index))
            for jID in iData.columns:
                jIDRawData = iRawData.loc[[jID]]
                for k in range(jIDRawData.shape[0]):
                    kStartDate = dt.datetime.strptime(jIDRawData["纳入日期"].iloc[k], "%Y%m%d").date()
                    kEndDate = (dt.datetime.strptime(jIDRawData["剔除日期"].iloc[k], "%Y%m%d").date()-dt.timedelta(1) if jIDRawData["剔除日期"].iloc[k] is not None else dt.date.today())
                    iData[jID].loc[kStartDate:kEndDate] = 1
            Data[iIndexID] = iData
        Data = pd.Panel(Data).ix[factor_names]
        Data.major_axis = [dt.datetime.combine(iDate, dt.time(23, 59, 59, 999999)) for iDate in Data.major_axis]
        Data.fillna(value=0, inplace=True)
        return _adjustDateTime(Data, dts, fillna=True, method="bfill")
    def _getRawData(self, fields, ids=None, start_date=None, end_date=None, args={}):
        IndexEquityID = self.FactorDB.ID2EquityID(fields)
        DBTableName = self.FactorDB.TablePrefix+self.FactorDB.TableName2DBTableName([self.Name])[self.Name]
        IDTable = self.FactorDB.TablePrefix+"tb_object_0001"
        FieldDict = self.FactorDB.FieldName2DBFieldName(table=self.Name, fields=['证券ID','指数ID','纳入日期','剔除日期','最新标志'])
        # 指数中成份股 ID, 指数证券 ID, 纳入日期, 剔除日期, 最新标志
        SQLStr = "SELECT "+DBTableName+'.'+FieldDict['指数ID']+', '# 指数证券 ID
        SQLStr += IDTable+".f1_0001, "# ID
        SQLStr += DBTableName+'.'+FieldDict['纳入日期']+', '# 纳入日期
        SQLStr += DBTableName+'.'+FieldDict['剔除日期']+', '# 剔除日期
        SQLStr += DBTableName+'.'+FieldDict['最新标志']+' '# 最新标志
        SQLStr += 'FROM '+DBTableName+', '+IDTable+" "
        SQLStr += 'WHERE '+DBTableName+'.'+FieldDict['证券ID']+'='+IDTable+'.f16_0001 '
        SQLStr += "AND ("+genSQLInCondition(DBTableName+'.'+FieldDict['指数ID'], list(IndexEquityID.values), is_str=True, max_num=1000)+") "
        if ids is not None:
            SQLStr += 'AND ('+genSQLInCondition(IDTable+'.f1_0001', ids, is_str=True, max_num=1000)+') '
        if start_date is not None:
            SQLStr += "AND (("+DBTableName+"."+FieldDict["剔除日期"]+">'"+start_date.strftime("%Y%m%d")+"') "
            SQLStr += "OR ("+DBTableName+"."+FieldDict["剔除日期"]+" IS NULL))"
        if end_date is not None:
            SQLStr += "AND "+DBTableName+"."+FieldDict["纳入日期"]+"<='"+end_date.strftime("%Y%m%d")+"' "
        else:
            SQLStr += "AND "+DBTableName+"."+FieldDict["纳入日期"]+" IS NOT NULL "
        SQLStr += 'ORDER BY '+DBTableName+'.'+FieldDict['指数ID']+", "+IDTable+'.f1_0001, '+DBTableName+'.'+FieldDict['纳入日期']
        RawData = self.FactorDB.fetchall(SQLStr)
        if RawData==[]:
            RawData = pd.DataFrame(columns=["指数ID", 'ID',  '纳入日期', '剔除日期', '最新标志'])
        else:
            RawData = pd.DataFrame(np.array(RawData),columns=["指数ID", 'ID', '纳入日期', '剔除日期', '最新标志'])
            for iID in fields:
                RawData["指数ID"][RawData["指数ID"]==IndexEquityID[iID]] = iID
        return RawData


class WindDB(FactorDB):
    """Wind 金融工程数据库"""
    DBType = Enum("SQL Server", "Oracle", "MySQL", arg_type="SingleOption", label="数据库类型", order=0)
    DBName = Str("wind", arg_type="String", label="数据库名", order=1)
    IPAddr = Str("127.0.0.1", arg_type="String", label="IP地址", order=2)
    Port = Range(low=0, high=65535, value=1521, arg_type="Integer", label="端口", order=3)
    User = Str("root", arg_type="String", label="用户名", order=4)
    Pwd = Password("shuntai11", arg_type="String", label="密码", order=5)
    TablePrefix = Str("", arg_type="String", label="表名前缀", order=6)
    CharSet = Enum("utf8", "gbk", "gb2312", "gb18030", "cp936", "big5", arg_type="SingleOption", label="字符集", order=7)
    Connector = Enum("default", "cx_Oracle", "pymssql", "mysql.connector", "pyodbc", arg_type="SingleOption", label="连接器", order=8)
    def __init__(self, sys_args={}, **kwargs):
        self._Connection = None# 数据库链接
        self._TableInfo = None# 数据库中的表信息
        self._FactorInfo = None# 数据库中的表字段信息
        self._InfoFilePath = None# 数据库信息文件路径
        self._AllTables = []# 数据库中的所有表名, 用于查询时解决大小写敏感问题
        super().__init__(sys_args=sys_args, **kwargs)
        self.Name = "WindDB"
        return
    def __getstate__(self):
        state = self.__dict__.copy()
        # Remove the unpicklable entries.
        state["_Connection"] = (True if self.isAvailable() else False)
        return state
    def __setstate__(self, state):
        self.__dict__.update(state)
        if self._Connection:
            self.connect()
        else:
            self._Connection = None
        self._AllTables = state.get("_AllTables", [])
    def __QS_initArgs__(self):
        ConfigFilePath = __QS_LibPath__+os.sep+"WindDBConfig.json"# 配置文件路径
        self._InfoFilePath = __QS_LibPath__+os.sep+"WindDBInfo.hdf5"# 数据库信息文件路径
        Config = readJSONFile(ConfigFilePath)
        ArgNames = self.ArgNames
        for iArgName, iArgVal in Config.items():
            if iArgName in ArgNames: self[iArgName] = iArgVal
        if not os.path.isfile(self._InfoFilePath):
            InfoResourcePath = __QS_MainPath__+os.sep+"Rescource"+os.sep+"WindDBInfo.xlsx"# 数据库信息源文件路径
            print("缺失数据库信息文件: '%s', 尝试从 '%s' 中导入信息." % (self._InfoFilePath, InfoResourcePath))
            if not os.path.isfile(InfoResourcePath): raise __QS_Error__("缺失数据库信息文件: %s" % InfoResourcePath)
            self.importInfo(InfoResourcePath)
        self._TableInfo = readNestedDictFromHDF5(self._InfoFilePath, ref="/TableInfo")
        self._FactorInfo = readNestedDictFromHDF5(self._InfoFilePath, ref="/FactorInfo")
    # -------------------------------------------数据库相关---------------------------
    def connect(self):
        if (self.Connector=='cx_Oracle') or ((self.Connector=='default') and (self.DBType=='Oracle')):
            try:
                import cx_Oracle
                self._Connection = cx_Oracle.connect(self.User, self.Pwd, cx_Oracle.makedsn(self.IPAddr, str(self.Port), self.DBName))
            except Exception as e:
                if self.Connector!='default': raise e
        elif (self.Connector=='pymssql') or ((self.Connector=='default') and (self.DBType=='SQL Server')):
            try:
                import pymssql
                self._Connection = pymssql.connect(server=self.IPAddr, port=str(self.Port), user=self.User, password=self.Pwd, database=self.DBName, charset=self.CharSet)
            except Exception as e:
                if self.Connector!='default': raise e
        elif (self.Connector=='mysql.connector') or ((self.Connector=='default') and (self.DBType=='MySQL')):
            try:
                import mysql.connector
                self._Connection = mysql.connector.connect(host=self.IPAddr, port=str(self.Port), user=self.User, password=self.Pwd, database=self.DBName, charset=self.CharSet)
            except Exception as e:
                if self.Connector!='default': raise e
        else:
            if self.Connector not in ('default', 'pyodbc'):
                self._Connection = None
                raise __QS_Error__("不支持该连接器(connector) : "+self.Connector)
            else:
                import pyodbc
                self._Connection = pyodbc.connect('DRIVER={%s};DATABASE=%s;SERVER=%s;UID=%s;PWD=%s' % (self.DBType, self.DBName, self.IPAddr, self.User, self.Pwd))
        self._AllTables = []
        return 0
    def disconnect(self):
        if self._Connection is not None:
            try:
                self._Connection.close()
            except Exception as e:
                raise e
            finally:
                self._Connection = None
        return 0
    def isAvailable(self):
        return (self._Connection is not None)
    def cursor(self, sql_str=None):
        if self._Connection is None: raise __QS_Error__("%s尚未连接!" % self.__doc__)
        Cursor = self._Connection.cursor()
        if sql_str is None: return Cursor
        if not self._AllTables:
            if self.DBType=="SQL Server":
                Cursor.execute("SELECT Name FROM SysObjects Where XType='U'")
                self._AllTables = [rslt[0] for rslt in Cursor.fetchall()]
            elif self.DBType=="MySQL":
                Cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='"+self.DBName+"' AND table_type='base table'")
                self._AllTables = [rslt[0] for rslt in Cursor.fetchall()]
        for iTable in self._AllTables:
            sql_str = re.sub(iTable, iTable, sql_str, flags=re.IGNORECASE)
        Cursor.execute(sql_str)
        return Cursor
    def fetchall(self, sql_str):
        Cursor = self.cursor(sql_str=sql_str)
        Data = Cursor.fetchall()
        Cursor.close()
        return Data
    # -------------------------------表的操作---------------------------------
    @property
    def TableNames(self):
        if self._TableInfo is not None: return self._TableInfo.index.tolist()
        else: return []
    def getTable(self, table_name, args={}):
        TableClass = self._TableInfo.loc[table_name, "TableClass"]
        return eval("_"+TableClass+"(name='"+table_name+"', fdb=self, sys_args=args)")
    # -----------------------------------------数据提取---------------------------------
    # 给定起始日期和结束日期, 获取交易所交易日期, 目前仅支持："上海证券交易所", "深圳证券交易所"
    def getTradeDay(self, start_date=None, end_date=None, exchange="上海证券交易所"):
        if exchange not in ("上海证券交易所", "深圳证券交易所"):
            raise __QS_Error__("不支持交易所：%s的交易日序列！" % exchange)
        if start_date is None:
            start_date = dt.date(1900,1,1)
        if end_date is None:
            end_date = dt.date.today()
        SQLStr = 'SELECT F1_1010 FROM {Prefix}tb_object_1010 '
        SQLStr += 'WHERE F1_1010<=\'{EndDate}\' '
        SQLStr += 'AND F1_1010>=\'{StartDate}\' '
        SQLStr += 'ORDER BY F1_1010'
        Dates = self.fetchall(SQLStr.format(Prefix=self.TablePrefix,StartDate=start_date.strftime("%Y%m%d"),EndDate=end_date.strftime("%Y%m%d")))
        return list(map(lambda x: dt.date(int(x[0][:4]), int(x[0][4:6]), int(x[0][6:8])), Dates))
    # 获取指定日当前在市或者历史上出现过的全体 A 股 ID
    def _getAllAStock(self, date, is_current=True):
        SQLStr = 'SELECT {Prefix}tb_object_0001.f1_0001 FROM {Prefix}tb_object_0001 INNER JOIN {Prefix}tb_object_1090 ON ({Prefix}tb_object_0001.f16_0001={Prefix}tb_object_1090.f2_1090) '
        if is_current:
            SQLStr += 'WHERE {Prefix}tb_object_1090.f21_1090=1 AND {Prefix}tb_object_1090.F4_1090=\'A\' AND ({Prefix}tb_object_1090.F18_1090 is NULL OR {Prefix}tb_object_1090.F18_1090>\'{Date}\') AND {Prefix}tb_object_1090.F17_1090<=\'{Date}\' ORDER BY {Prefix}tb_object_0001.f1_0001'
        else:
            SQLStr += 'WHERE {Prefix}tb_object_1090.f21_1090=1 AND {Prefix}tb_object_1090.F4_1090=\'A\' AND {Prefix}tb_object_1090.F17_1090<=\'{Date}\' ORDER BY {Prefix}tb_object_0001.f1_0001'
        return [iRslt[0] for iRslt in self.fetchall(SQLStr.format(Prefix=self.TablePrefix, Date=date.strftime("%Y%m%d")))]
    # 给定指数名称和ID，获取指定日当前或历史上的指数中的股票ID，is_current=True:获取指定日当天的ID，False:获取截止指定日历史上出现的ID
    def getID(self, index_id="全体A股", date=None, is_current=True):
        if date is None:
            date = dt.date.today()
        if index_id=="全体A股":
            return self._getAllAStock(date=date,is_current=is_current)
        # 获取指数在数据库内部的证券 ID
        SQLStr = 'SELECT f16_0001 FROM {Prefix}tb_object_0001 where f1_0001=\'{IndexID}\''
        IndexEquityID = self.fetchall(SQLStr.format(Prefix=self.TablePrefix, IndexID=index_id))[0][0]
        # 获取指数中的股票 ID
        SQLStr = 'SELECT {Prefix}tb_object_0001.f1_0001 FROM {Prefix}tb_object_1402, {Prefix}tb_object_0001 '
        SQLStr += 'WHERE {Prefix}tb_object_0001.F16_0001={Prefix}tb_object_1402.F1_1402 '
        SQLStr += 'AND {Prefix}tb_object_1402.F2_1402=\'{IndexEquityID}\' '
        SQLStr += 'AND {Prefix}tb_object_1402.F3_1402<=\'{Date}\' '# 纳入日期在date之前
        if is_current:
            SQLStr += 'AND ({Prefix}tb_object_1402.F5_1402=1 OR {Prefix}tb_object_1402.F4_1402>\'{Date}\') '# 剔除日期在date之后
        SQLStr += 'ORDER BY {Prefix}tb_object_0001.f1_0001'
        return [iRslt[0] for iRslt in self.fetchall(SQLStr.format(Prefix=self.TablePrefix, IndexEquityID=IndexEquityID, Date=date.strftime("%Y%m%d")))]
    # --------------------------------------------信息转换-----------------------------------
    # 将表名转换成数据库内部表名
    def TableName2DBTableName(self, table_names):
        return dict(self._TableInfo['DBTableName'][table_names])
    # 获取字段在数据库内部字段名
    def FieldName2DBFieldName(self, table, fields=[]):
        return dict(self._FactorInfo['DBFieldName'].ix[table].ix[fields])
    # ID 转换成证券 ID
    def ID2EquityID(self, ids):
        nID = len(ids)
        if nID<=1000:
            SQLStr = 'SELECT f1_0001, f16_0001 FROM '+self.TablePrefix+'tb_object_0001 WHERE f1_0001 IN (\''+'\',\''.join(ids)+'\')'
        else:
            SQLStr = 'SELECT f1_0001, f16_0001 FROM '+self.TablePrefix+'tb_object_0001 WHERE f1_0001 IN (\''+'\',\''.join(ids[0:1000])+'\')'
            i = 1000
            while i<nID:
                SQLStr += ' OR f1_0001 IN (\''+'\',\''.join(ids[i:i+1000])+'\')'
                i = i+1000
        Cursor = self.cursor(SQLStr)
        Result = Cursor.fetchall()
        Cursor.close()
        return dict(Result)
    # 证券 ID 转换成 ID
    def EquityID2ID(self, equity_ids):
        nID = len(equity_ids)
        if nID<=1000:
            SQLStr = 'SELECT f16_0001, f1_0001 FROM '+self.TablePrefix+'tb_object_0001 WHERE f16_0001 IN (\''+'\',\''.join(equity_ids)+'\')'
        else:
            SQLStr = 'SELECT f16_0001, f1_0001 FROM '+self.TablePrefix+'tb_object_0001 WHERE f16_0001 IN (\''+'\',\''.join(equity_ids[0:1000])+'\')'
            i = 1000
            while i<nID:
                SQLStr += ' OR f16_0001 IN (\''+'\',\''.join(equity_ids[i:i+1000])+'\')'
                i = i+1000
        return dict(self.fetchall(SQLStr))
    # 获取行业名称和对应的数据库内部代码, {行业名称:数据库内部代码}
    def getIndustryDBInnerID(self, industry_class_name='中信行业', level=1):
        if industry_class_name=='中信行业':
            SQLStr = 'SELECT NAME, CODE FROM '+self.TablePrefix+'TB_OBJECT_1022 WHERE CODE LIKE \'b1%\' AND LEVELNUM='+str(level+1)
        elif industry_class_name=='申万行业':
            SQLStr = 'SELECT NAME, CODE FROM '+self.TablePrefix+'TB_OBJECT_1022 WHERE CODE LIKE \'61%\' AND LEVELNUM='+str(level+1)
        elif industry_class_name=='Wind行业':
            SQLStr = 'SELECT NAME, CODE FROM '+self.TablePrefix+'TB_OBJECT_1022 WHERE CODE LIKE \'62%\' AND LEVELNUM='+str(level+1)
        elif industry_class_name=='中信一级行业':
            SQLStr = 'SELECT NAME, CODE FROM '+self.TablePrefix+'TB_OBJECT_1022 WHERE CODE LIKE \'b1%\' AND LEVELNUM=2'
        elif industry_class_name=='申万一级行业':
            SQLStr = 'SELECT NAME, CODE FROM '+self.TablePrefix+'TB_OBJECT_1022 WHERE CODE LIKE \'61%\' AND LEVELNUM=2'
        elif industry_class_name=='Wind一级行业':
            SQLStr = 'SELECT NAME, CODE FROM '+self.TablePrefix+'TB_OBJECT_1022 WHERE CODE LIKE \'62%\' AND LEVELNUM=2'
        Cursor = self.cursor(SQLStr)
        Rslt = Cursor.fetchall()
        Cursor.close()
        return dict(Rslt)
    # 将 Excel 文件中的表和字段信息导入信息文件
    def importInfo(self, excel_file_path):
        DF = pd.read_excel(excel_file_path, "TableInfo").set_index(["TableName"])
        writeNestedDict2HDF5(DF, self._InfoFilePath, "/TableInfo")
        DF = pd.read_excel(excel_file_path, 'FactorInfo').set_index(['TableName', 'FieldName'])
        writeNestedDict2HDF5(DF, self._InfoFilePath, "/FactorInfo")