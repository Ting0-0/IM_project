from gurobipy import *
import numpy as np
import pandas as pd
import data.tool as tl
import datetime, calendar
#=============================================================================#
# 11/25 更新：
#   ＊修正utf-8的csv檔打開會亂碼的問題
#   ＊休假班別代號：由0改成O
#   ＊上班日：從進線預測資料自動抓上班日期（有預測就表示要上班。允許周末上班）
#   ＊每周晚班次數限制：改成每人可以有不同上限（從data裡的EMPLOYEE讀取）
#=============================================================================#


#=============================================================================#
# settings 方便隨時修改的部分
#=============================================================================#
year = 2019
month = 1
#=============================================================================#
#import data
dir_name = './data/'
result_x = './排班結果.csv'
result_y = './冗員與缺工人數.csv'
result = './其他資訊.xlsx'
#basic
A_t = pd.read_csv(dir_name + 'fix_class_time.csv', header = 0, index_col = 0)
DEMAND_t = pd.read_csv(dir_name+"進線人力.csv", header = 0, index_col = 0).T
DATES = [ int(x) for x in DEMAND_t.index ]    #所有的日期 - 對照用
print('DATES = ',end='')
print(DATES)
#employees data
EMPLOYEE_t = pd.read_csv(dir_name+"EMPLOYEE.csv", header = 0) 




#####NM 及 NW 從人壽提供之上個月的班表裡面計算(郭？)
NM_t = EMPLOYEE_t['NM']
NW_t = EMPLOYEE_t['NW']
#####




E_NAME = list(EMPLOYEE_t['name_English'])   #E_NAME - 對照名字與員工index時使用
E_SENIOR_t = EMPLOYEE_t['Senior']
E_POSI_t = EMPLOYEE_t['Position']
E_SKILL_t = EMPLOYEE_t[['skill-phone','skill-CD','skill-chat','skill-outbound']]
SKILL_NAME = list(E_SKILL_t.columns)        #SKILL_NAME - 找員工組合、班別組合時使用

P_t = pd.read_csv(dir_name + '軟限制權重.csv', header = None, index_col = 0) 

#const
Kset_t = pd.read_csv(dir_name + 'fix_classes.csv', header = None, index_col = 0) #class set
SKset_t = pd.read_csv(dir_name + 'skills_classes.csv', header = None, index_col = 0) #class set for skills
M_t = pd.read_csv(dir_name+"特定班別、休假.csv", header = None, skiprows=[0])
L_t = pd.read_csv(dir_name+"下限.csv", header = None, skiprows=[0])
U_t = pd.read_csv(dir_name+"上限.csv", header = None, skiprows=[0])
Ratio_t = pd.read_csv(dir_name+"CSR年資占比.csv",header = None, skiprows=[0])
SENIOR_bp = Ratio_t[3]
timelimit = pd.read_csv(dir_name+"時間限制.csv", header = 0)
nightdaylimit = EMPLOYEE_t['night_perWeek'] #pd.read_csv(dir_name+"晚班天數限制.csv", header = 0).loc[0][0]

#============================================================================#
# Create a new model
m = Model("first")
#============================================================================#
#Indexs 都從0開始

#i 員工 i
#j 日子 j，代表一個月中的需要排班的第 j 個日子
#k 班別 k，代表每天可選擇的不同上班別態
#t 工作時段 t，表示某日的第 t 個上班的小時
#w 週次 w，代表一個月中的第 w 週
#r 午休方式r，每個班別有不同的午休方式

#休假:0
#早班-A2/A3/A4/A5/MS/AS:1~6
#午班-P2/P3/P4/P5:7~10
#晚班-N1/M1/W6:11~13
#其他-CD/C2/C3/C4/OB:14~18

#============================================================================#
#Parameters
#-------number-------#
nEMPLOYEE = EMPLOYEE_t.shape[0]     #總員工人數
nDAY = len(DEMAND_t.index)          #總日數
nK = 19                             #班別種類數
nT = 24                             #總時段數
nR = 5                              #午休種類數
nW = tl.get_nW(year,month)          #總週數

nPOSI = 4                       	    #職稱數量 (=擁有特定職稱的總員工集合數
nSKILL = 4                          	#nVA技能數量 (=擁有特定技能的總員工集合數

#-------Basic-------#
CONTAIN = A_t.values.tolist()      #CONTAIN_kt - 1表示班別k包含時段t，0則否

DEMAND = DEMAND_t.values.tolist()  #DEMAND_jt - 日子j於時段t的需求人數
ASSIGN = []                        #ASSIGN_ijk - 員工i指定第j天須排班別k，形式為 [(i,j,k)]

for c in range(M_t.shape[0]):
    e = tl.TranName_t2n(M_t.iloc[c,0], E_NAME)
    k = tl.TranK_t2n( str(M_t.iloc[c,2]) )
    d = tl.TranName_t2n(M_t.iloc[c,1], DATES)
    ASSIGN.append( (e, d, k) )

LMNIGHT = NM_t.values            #LMNIGHT_i - 表示員工i在上月終未滿一週的日子中曾排幾次晚班
FRINIGHT = NW_t.values           #FRINIGHT_i - 1表示員工i在上月最後一日且為週五的日子排晚班，0則否
# -------調整權重-------#
P0 = 100    					#目標式中的調整權重(lack)
P1 = P_t[1]['P1']    			#目標式中的調整權重(surplus)
P2 = P_t[1]['P2']   	    	#目標式中的調整權重(nightCount)
P3 = P_t[1]['P3']    	   		#目標式中的調整權重(breakCount)
P4 = P_t[1]['P4']    	 		#目標式中的調整權重(complement)

#-----排班特殊限制-----#
LOWER = L_t.values.tolist()       	#LOWER - 日期j，班別集合ks，職位p，上班人數下限
for i in range(len(LOWER)):
    d = tl.TranName_t2n( LOWER[i][0], DATES)
    LOWER[i][0] = d
UPPER = U_t.values.tolist()       	#UPPER - 員工i，日子集合js，班別集合ks，排班次數上限
PERCENT = Ratio_t.values.tolist()	#PERCENT - 日子集合，班別集合，要求占比，年資分界線

#============================================================================#
#Sets
EMPLOYEE = [tmp for tmp in range(nEMPLOYEE)]    #EMPLOYEE - 員工集合，I=1,…,nI 
DAY = [tmp for tmp in range(nDAY)]              #DAY - 日子集合，J=0,…,nJ-1
TIME = [tmp for tmp in range(nT)]               #TIME - 工作時段集合，T=1,…,nT
BREAK = [tmp for tmp in range(nR)]              #BREAK - 午休方式，R=1,…,nR
WEEK = [tmp for tmp in range(nW)]               #WEEK - 週次集合，W=1,…,nW
SHIFT = [tmp for tmp in range(nK)]              #SHIFT - 班別種類集合，K=1,…,nK ;0代表休假
 
#-------員工集合-------#
E_POSITION = tl.SetPOSI(E_POSI_t)                                #E_POSITION - 擁有特定職稱的員工集合，POSI=1,…,nPOSI
E_SKILL = tl.SetSKILL(E_SKILL_t)                                 #E_SKILL - 擁有特定技能的員工集合，SKILL=1,…,nSKILL
E_SENIOR = [tl.SetSENIOR(E_SENIOR_t,tmp) for tmp in SENIOR_bp]   #E_SENIOR - 達到特定年資的員工集合    

#-------日子集合-------#
month_start = tl.get_startD(year,month)         #本月第一天是禮拜幾 (Mon=0, Tue=1..)
D_WEEK = tl.SetDAYW(month_start+1,nDAY,nW)  	#D_WEEK - 第 w 週中所包含的日子集合
D_MONFRI = tl.SetDAYW_fri(D_WEEK,nW)        	#D_MONFRI - 第 w 週中星期五與下週星期一的日子集合
DAYset = tl.SetDAY(month_start, nDAY)     		#DAYset - 通用日子集合 [all,Mon,Tue...]

#-------班別集合-------#
S_NIGHT = [11, 12, 13]                                          #S_NIGHT - 所有的晚班
S_BREAK = [[11,12],[1,7,14,15],[2,8,16,18],[3,9,17],[4,10]]     #Kr - 午休方式為 r 的班別 
SHIFTset= {}                                                    #SHIFTset - 通用的班別集合，S=1,…,nS
for ki in range(len(Kset_t)):
    SHIFTset[Kset_t.index[ki]] = [ tl.TranK_t2n(x) for x in Kset_t.iloc[ki].dropna().values ]
K_skill_not = []                                                #K_skill_not - 各技能的優先班別的補集
for ki in range(len(SKset_t)):
    sk = [ tl.TranK_t2n(x) for x in SKset_t.iloc[ki].dropna().values ]  #各個技能的優先班別
    K_skill_not.append( list( set(range(0,nK)).difference(set(sk)) ) )      #非優先的班別


#============================================================================#
#Variables
#GRB.BINARY/GRB.INTEGER/GRB.CONTINUOUS

work = {}  #work_ijk - 1表示員工i於日子j值班別為k的工作，0 則否 ;workij0=1 代表員工i在日子j休假
for i in range(nEMPLOYEE):
    for j in range(nDAY):
        for k in range(nK):
            work[i, j, k] = m.addVar(vtype=GRB.BINARY)  
            
lack = {}  #y_jt - 代表第j天中時段t的缺工人數
for j in range(nDAY):
    for t in range(nT):
        lack[j, t] = m.addVar(lb=0, vtype=GRB.CONTINUOUS)
        
surplus = m.addVar(lb=0,vtype=GRB.CONTINUOUS, name="surplus") #每天每個時段人數與需求人數的差距中的最大值
nightCount = m.addVar(lb=0,vtype=GRB.CONTINUOUS, name="nightCount") #員工中每人排晚班總次數的最大值

breakCount = {}  #breakCount_iwr - 1表示員工i在第w周中在午休時段r有午休，0則否
for i in range(nEMPLOYEE):
    for w in range(nW):
        for r in range(nR):
            breakCount[i, w, r] = m.addVar(vtype=GRB.BINARY)


complement =  m.addVar(lb=0,vtype=GRB.CONTINUOUS, name="complement")  #complement - 擁有特定員工技能的員工集合va的員工排非特定班別數的最大值

m.update()

#============================================================================#
#Objective

m.setObjective(P0 * quicksum(lack[j,t] for t in TIME for j in DAY) +  P1 * surplus + P2 * nightCount + \
    P3 * quicksum(breakCount[i,w,r] for i in EMPLOYEE for w in WEEK for r in BREAK) + \
               P4 *complement , GRB.MINIMIZE)

#============================================================================#
#Constraints

#2 每人每天只能排一種班別
for i in EMPLOYEE:
    for j in DAY:
        m.addConstr(quicksum(work[i,j,k] for k in SHIFT) == 1, "c2")

#4 指定日子排指定班別
for c in ASSIGN:
    m.addConstr(work[c[0],c[1],c[2]] == 1, "c4")

#5 除第一周外，每周最多n次晚班
no_week1 = WEEK.copy()
no_week1.remove(0)            
for i in EMPLOYEE:
    for w in no_week1:
        m.addConstr(quicksum(work[i,j,k] for j in D_WEEK[w] for k in S_NIGHT) <= nightdaylimit[i], "c5")
                    
#6 上月斷頭周+本月第一周 只能n次晚班
for i in EMPLOYEE:
    m.addConstr(quicksum(work[i,j,k] for j in D_WEEK[0] for k in S_NIGHT) <= nightdaylimit[i] - LMNIGHT[i], "c6")

#7 周五、下周一只能一次晚班
less_one_week = WEEK.copy()       
less_one_week.pop()
for i in EMPLOYEE:
    for w in less_one_week:
        m.addConstr(quicksum(work[i,j,k] for j in D_MONFRI[w] for k in S_NIGHT) <= 1, "c7")
        
#8 上月末日為週五且晚班，則本月初日不能晚班 
for i in EMPLOYEE:
    m.addConstr(quicksum(work[i,0,k] for k in S_NIGHT) <= 1 - FRINIGHT[i], "c8")        

#9 限制職等的人數下限：每一個特定日子，特定班別、特定一個職等的合計人數 >= 下限
#與原式較不同
for item in LOWER:
    m.addConstr(quicksum(work[i,item[0],k] for i in E_POSITION[item[2]] for k in SHIFTset[item[1]]) >= item[3],"c9")

#10 排班次數上限：員工在特定日子、特定班別，排班不能超過多少次
#與原式較不同
for item in UPPER:
    for i in EMPLOYEE:	
        m.addConstr(quicksum(work[i,j,k] for j in DAYset[item[0]] for k in SHIFTset[item[1]]) <= item[2], "c10")     
       
#11 計算缺工人數
for j in DAY:
    for t in TIME:    
        m.addConstr(lack[j,t] >= -(quicksum(CONTAIN[k][t] * work[i,j,k] for k in SHIFT for i in EMPLOYEE) - DEMAND[j][t]), "c11")         

#13 避免冗員
for j in DAY:
    for t in TIME:
        m.addConstr(surplus >= quicksum(CONTAIN[k][t] * work[i,j,k] for k in SHIFT for i in EMPLOYEE) - DEMAND[j][t], "c13")        

#14 平均每人的晚班數
for i in EMPLOYEE:
    m.addConstr(nightCount >= quicksum(work[i,j,k]  for k in S_NIGHT for j in DAY), "c14")


#15 同一人同一周休息時間盡量相同
for i in EMPLOYEE:
    for w in WEEK:
        for r in BREAK:
             m.addConstr(5*breakCount[i,w,r] >= quicksum(work[i,j,k]  for k in S_BREAK[r] for j in D_WEEK[w]), "c15") 

#16 chat技能的員工優先排類型為「其他」的班別
m.addConstr(complement >= quicksum(work[i,j,k] for k in K_skill_not[2] for j in DAY for i in E_SKILL['chat']),"c16")

             
#17晚班年資2年以上人數需佔 50% 以上
for ix,item in enumerate(PERCENT):
    for j in DAYset[item[0]]:
        for k in SHIFTset[item[1]]:
            m.addConstr(quicksum(work[i,j,k] for i in E_SENIOR[ix]) >= item[2]*quicksum(work[i,j,k] for i in EMPLOYEE),"c17")

#12,18,19 已在variable限制    
#============================================================================#
#process
m.params.TimeLimit = timelimit.loc[0][0]
m.optimize()


#============================================================================#
#print out
#============================================================================#

#Dataframe_x
K_type = ['O','A2','A3','A4','A5','MS','AS','P2','P3','P4','P5','N1','M1','W6','CD','C2','C3','C4','OB']


employee_name = E_NAME #[tmp+1 for tmp in EMPLOYEE]
# which_day = [tmp+1 for tmp in DAY]
which_worktime = []
for i in EMPLOYEE:
    tmp = []
    for j in DAY:
        for k in SHIFT:
            if(work[i,j,k].x==1):
                tmp.append(K_type[k])
                break
        else:
            print('Warning! Employee',i,'(',E_NAME[i],') in day',DATES[j],'do not have any class\n')
            # print('Warning! Employee',i,'(',E_NAME[i],') in day',(nDAY-j+1),'do not have any class\n')
    which_worktime.append(tmp)
        

df_x = pd.DataFrame(which_worktime, index = employee_name, columns = DATES) #which_day)
# print("\n\n====================員工排班表/row = 員工/col = 第幾天====================\n")
# print(df_x)


#Dataframe_y
T_type = ['09:00','09:30','10:00','10:30','11:00','11:30','12:00','12:30','13:00','13:30','14:00','14:30'
        ,'15:00','15:30','16:00','16:30','17:00','17:30','18:00','18:30','19:00','19:30','20:00','20:30']

lesspeople_count = []
for j in DAY:
    tmp = []
    for t in TIME:
        tmp.append(int(lack[j,t].x))
    lesspeople_count.append(tmp)


df_y = pd.DataFrame(lesspeople_count, index = DATES, columns = T_type) #which_day , columns = T_type)

#計算總和
df_y['SUM_per_day'] = df_y.sum(axis=1)
df_y.loc['SUM_per_time'] = df_y.sum()

#計算需求
demand_day = DEMAND_t.sum(axis=1).values
demand_time = DEMAND_t.sum().values
#計算缺工比例
less_percent_day = (df_y['SUM_per_day'].drop(['SUM_per_time']).values)/demand_day
less_percent_time = (df_y.loc['SUM_per_time'].drop(['SUM_per_day']).values)/demand_time
df_percent_day = pd.DataFrame(less_percent_day, index = DATES, columns = ["Percentage"]) #which_day , columns = ["Percentage"])
df_percent_time = pd.DataFrame(less_percent_time, index = T_type , columns = ["Percentage"])

# print("\n====================缺工人數表/row = 第幾天/col = 時段====================\n")
# print(df_y)

# print("\n====================每天缺工百分比表/row = 第幾天====================\n")
# print(df_percent_day)

# print("\n====================每個時段缺工百分比表/row = 時段====================\n")
# print(df_percent_time)

#h1h2
print("\n所有天每個時段人數與需求人數的差距中的最大值 = "+str(int(surplus.x))+"\n")



#晚班次數dataframe
night_work_total = []
for i in EMPLOYEE:
    count = 0
    for j in DAY:
        for k in range(11,14):
            if(int(work[i,j,k].x)==1):
                count+=1
    night_work_total.append(count)


df_nightcount = pd.DataFrame(night_work_total, index = employee_name, columns = ['NW_count'])
# print("\n====================員工本月晚班次數/row = 員工====================\n")
# print(df_nightcount)
print("\n員工中每人排晚班總次數的最大值 = "+str(int(nightCount.x))+"\n")



      
#Dataframe_z
R_type = ['11:30','12:00','12:30','13:00','13:30']     
which_week = [tmp+1 for tmp in WEEK] 
which_resttime = []     
for i in EMPLOYEE:
    tmp = []
    for w in WEEK:
        tmp2 = []
        for r in BREAK:
            if(breakCount[i,w,r].x==1):
                tmp2.append(R_type[r])
        tmp.append(tmp2)
    which_resttime.append(tmp)


df_resttime = pd.DataFrame(which_resttime, index=employee_name, columns=which_week)
# print("\n====================員工每週有哪幾種休息時間/row = 員工/col = 周次====================\n")
# print(df_resttime)

print("Final MIP gap value: %f" % m.MIPGap)
print("\n目標值 = "+str(m.objVal) + "\n")


#============================================================================#
#輸出其他資訊
with pd.ExcelWriter(result) as writer:
    df_x.to_excel(writer, sheet_name="員工排班表")
    df_nightcount.to_excel(writer, sheet_name="員工本月晚班次數")
    df_percent_time.to_excel(writer, sheet_name="每個時段缺工百分比表")
    df_percent_day.to_excel(writer, sheet_name="每天缺工百分比表")
    df_nightcount.to_excel(writer, sheet_name="員工本月晚班次數")
    df_y.to_excel(writer, sheet_name="缺工人數表")
    df_resttime.to_excel(writer, sheet_name="員工每週有哪幾種休息時間")

#============================================================================#
#輸出班表
output_name = []
for i in range(0,nEMPLOYEE):
    output_name.append(str(EMPLOYEE_t.id.values.tolist()[i]) + EMPLOYEE_t.name_Chinese.values.tolist()[i])
mDAY = int(calendar.monthrange(year,month)[1])
date_list = []
date_name = []
for i in range(1,mDAY+1): #產生日期清單
    date = datetime.datetime.strptime(str(year)+'-'+str(month)+'-'+str(i), "%Y-%m-%d")
    date_list.append(date)
    date_name.append(date.strftime("%Y-%m-%d"))
new = pd.DataFrame()
NO_WORK=[]
for i in range(0,nEMPLOYEE): #假日全部填X
    NO_WORK.append("X")
# j = 1
for i in range(0,mDAY):
    if (i+1) not in DATES: #date_list[i].weekday()==5 or date_list[i].weekday()==6:
        new[date_name[i]] = NO_WORK
    else:
        new[date_name[i]] = df_x[i+1].values.tolist()
        # new[date_name[i]] = df_x[j].values.tolist()
        # j = j + 1
print('check point 2\n')
new['name']=output_name
new.set_index("name",inplace=True)
new.to_csv(result_x, encoding="utf-8_sig")
print(new)

#============================================================================#
#輸出冗員與缺工人數表

K_type_dict = {1:'O',2:'A2',3:'A3',4:'A4',5:'A5',6:'MS',7:'AS',8:'P2',9:'P3',10:'P4',11:'P5',12:'N1',13:'M1',14:'W6',15:'CD',16:'C2',17:'C3',18:'C4',19:'OB'}
x_nb = np.vectorize({v: k for k, v in K_type_dict.items()}.get)(np.array(which_worktime))
people = np.zeros((nDAY,24))
for i in range(0,nEMPLOYEE):
    for j in range(0,nDAY):
        for k in range(0,24):
            people[j][k] = people[j][k] + A_t.values[x_nb[i][j]-1][k]
output_people = (people - DEMAND).tolist()
NO_PEOPLE=[]
new_2=pd.DataFrame()
for i in range(0,24):
    NO_PEOPLE.append('X')
j = 0
for i in range(0,mDAY):
    if date_list[i].weekday()==5 or date_list[i].weekday()==6:
        new_2[date_name[i]]=NO_PEOPLE
    else:
        new_2[date_name[i]]=output_people[j]
        j = j + 1
new_2['name']=T_type
new_2.set_index("name",inplace=True)
new_2.to_csv(result_y, encoding="utf-8_sig")
# print(new_2.T)

#============================================================================#


