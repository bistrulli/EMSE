import sys
import glob
import subprocess
import os
import shutil
import itertools
import time
import re
import queue
from pathlib import Path


VERBOSE = False
SAVE_LOGS = True
PRINT_LOGS = False
LOG_FILENAME = 'preproc.log'
PREPROC_DIR = 'preprocessed_fast/'
HOME_DIR = '/workspace/EMSE/'

stime=None



def printProgressBar(iteration, total, prefix='', suffix='', decimals=1, length=100, fill='█', printEnd='\r'):
	"""
	Call in a loop to create terminal progress bar
	@params:
	iteration   - Required  : current iteration (Int)
	total       - Required  : total iterations (Int)
	prefix      - Optional  : prefix string (Str)
	suffix      - Optional  : suffix string (Str)
	decimals    - Optional  : positive number of decimals in percent complete (Int)
	length      - Optional  : character length of bar (Int)
	fill        - Optional  : bar fill character (Str)
	printEnd    - Optional  : end character (e.g. "\r", "\r\n") (Str)
	"""
	#percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
	ratio = ("{}/{}".format(iteration, total))
	filledLength = int(length * iteration // total)
	bar = fill * filledLength + '-' * (length - filledLength)
	print('\r%s |%s| %s %s' % (prefix, bar, ratio, suffix), end = printEnd)
	# Print New Line on Complete
	if iteration == total: 
		print()





# Check that one or two inputs are provided
def checkNumberInputs(params):
	if len(params) < 2 or len(params) > 3:
		print('One or two parameters are required:')
		print('1) The main directory from where all C and H files can be found')
		print('2) [Optional] The sub-directory from where C files must be looked for OR the C file to analyze. If this parameter is not provided, it will be set to the main directory')
		sys.exit(-1)



def removeIfLink(filepaths):
	notlinks = [];
	for filepath in filepaths:
		if not os.path.islink(filepath) and not os.path.isdir(filepath):
			notlinks.append(filepath)
		else:
			if(os.path.isdir(filepath)):
				print("dir")
			else:
				print("link")
	return notlinks




def getInputs(params):

	# Check the first input is a directory
	if not os.path.isdir(params[1]):
		print('The first parameter must be a directory')
		sys.exit(-1)
	else:
		if params[1][-1] != '/':
			path = params[1] + '/'
		else:
			path = params[1]
			
	# Check the second input (only if it is provided)
	if len(params) == 3:
		if not (os.path.isdir(params[2]) or os.path.isfile(params[2])):
			print('If provided, the second parameter must be a file or a directory')
			sys.exit(-1)
		elif os.path.isfile(params[2]):
			if params[2][-2:] == '.c':
				cFiles = [params[2]]
			else:
				print('If the second parameter is a file, then it must be a C file')
				sys.exit(-1)
		else:
			if params[2][-1] != '/':
				#cFiles = glob.glob(params[2] + '/**/*.c', recursive=True)
				proc = subprocess.Popen(['find', params[2], '-name', '*.c'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
				cFiles, _ = proc.communicate()
				cFiles = cFiles.decode('utf-8', errors='ignore').split('\n')
				if cFiles[-1] == '':
					cFiles = cFiles[:-1]
			else:
				#cFiles = glob.glob(params[2] + '**/*.c', recursive=True)
				proc = subprocess.Popen(['find', params[2] + '/', '-name', '*.c'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
				cFiles, _ = proc.communicate()
				cFiles = cFiles.decode('utf-8', errors='ignore').split('\n')
				if cFiles[-1] == '':
					cFiles = cFiles[:-1]
	else:
		#cFiles = glob.glob(path + '**/*.c', recursive=True)
		proc = subprocess.Popen(['find', path, '-name', '*.c'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		cFiles, _ = proc.communicate()
		cFiles = cFiles.decode('utf-8', errors='ignore').split('\n')
		if cFiles[-1] == '':
			cFiles = cFiles[:-1]
	return path, removeIfLink(cFiles)
	



def ignore_files(dir, files):
	return [f for f in files if os.path.isfile(os.path.join(dir, f))]
	
	
	
def printAndSave(string, logfilename, saveString, printString):
	if saveString:
		with open(logfilename, 'a') as f:
			f.write(string + '\n')
	if printString:
		print(string)
		
		
def printDebug(string, verbose):
	if verbose:
		print(string)
		
	
	
	
def cleanDependencies(deps, filepath):
	exclude = [filepath, '', '\\']
	deps = [x for x in deps if x not in exclude]
#	print('??? ', deps)
	exclude = []
	for dep in deps:
		if os.path.exists(dep):
			exclude.append(dep)
	deps = [x for x in deps if x not in exclude]
	return deps
	
	
	
#def depth_list(lst):
#    if lst:
#        return isinstance(lst, list) and max(map(depth_list, lst)) + 1
#    else:
#        return 1
#    
#    
#def flatten_list(lst):
#    out = []
#    for l in lst:
#        if depth_list(l) == 1:
#            out += [l]
#        elif depth_list(l) == 2:
#            out += l
#        else:
#            out += flatten_list(l)
#    return out




def keepDependencyPath(libpath, dep):
	#return '/'.join(libpath.split('/')[:-1])
	return libpath.replace(dep, '')
	
	
	
def removeDuplicates(deplist):
	deplist = set(map(tuple, deplist))
	return list(map(list, deplist))
	
	
def getAllCombinations(deplist):
	return list(map(list, itertools.product(*deplist)))
	
	
def removeEmptySublists(deplist):
	exclude = []
	for dep in deplist:
		if len(dep) == 0:
			exclude.append(dep)
	return [x for x in deplist if x not in exclude]




def exploreDependenciesTreeBFS(path, filepath, deps=list()):
#	tree = []
	deplist = getDependencies(filepath, deps=deps)
	pathlist = []
	for dep in deplist:
		libpaths = glob.glob(path + '**/' + dep, recursive=True)
		libpaths = removeIfLink(libpaths)
		onlylibpaths = [keepDependencyPath(libpath, dep) for libpath in libpaths]
		pathlist.append(onlylibpaths)
#		print('* ', dep)
#		print('** ', pathlist)
		#input()
	pathlist = removeEmptySublists(getAllCombinations(removeDuplicates(pathlist)))
#	print('*** ', pathlist)
	#sys.exit(-1)
	tmplist = []
	for i in range(len(pathlist)):
		new_combos = exploreDependenciesTreeBFS(path, filepath, deps=deps+pathlist[i])
#		print('+++ ', new_combos)
		if len(new_combos) > 0:
			for combo in new_combos:
				tmplist.append(pathlist[i] + combo)
		else:
			tmplist.append(pathlist[i])
	pathlist = [x for x in tmplist]
	del tmplist
	return pathlist
	
	
	
def allHeadersExist(filepath):
	headers = getDependencies(filepath)
	for header in headers:
		header = header.replace('[space_tag]', ' ')
		headerpaths = glob.glob(path + '**/' + header, recursive=True)
		headerpaths = removeIfLink(headerpaths)
		if len(headerpaths) == 0:
				return False, header
	return True, None
#	with open(filepath, 'r') as f:
#		lines = f.readlines()
#	for line in lines:
#		if '#include' in line:
#			if '"' in line:
#		 		header = line.split('"')[1]
#			elif '<' in line:
#		 		header = line.split('<')[1].split('>')[0]
#			headerpaths = glob.glob(path + '**/' + header, recursive=True)
#			if len(headerpaths) == 0:
#				return False, header
#	return True, None
	
	
def exploreDependenciesTreeDFS(path, cFilePath, destFolder, deps=list()):
	keepGoing = True
	if len(deps) == 0:
		keepGoing, missingHeader = allHeadersExist(cFilePath)
	if keepGoing:
		cmdList = ['cpp', '-M', cFilePath]
		for dep in deps:
			cmdList += ['-I', dep]
		printDebug('[DEBUG] Dependencies: ' + ' '.join(cmdList), VERBOSE)
		proc = subprocess.Popen(cmdList, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		_, err = proc.communicate()
		errStr = err.decode('utf-8', errors='ignore')
		if '#include' in errStr:
			for line in errStr.split('\n'):
				if '#include' in line:
					deppaths = None;
					if '"' in line:
						# case user defined include
						newDep = line.split('"')[1]
						filepath = '/'.join(cFilePath.split('/')[:-1])
						#deppaths = glob.glob(filepath + '/' + newDep, recursive=False);
						deppaths=[]
					if deppaths is None:
						#system defined include
						if '<' in line:
							newDep = line.split('<')[1].split('>')[0]
						#deppaths = glob.glob(path + '**/' + newDep, recursive=True)
						deppaths=[]
						#print('<>', newDep, deppaths)
					elif len(deppaths) == 0:
						pass
						#deppaths = glob.glob(path + '**/' + newDep, recursive=True)
						#print('<>', newDep, deppaths)
					deppaths = removeIfLink(deppaths);
					for deppath in deppaths:
						keepGoing, missingHeader = allHeadersExist(deppath)
						if keepGoing:
							deppath = deppath[:-len(newDep)]
							#deppath = deppath.replace(newDep, '')
							printDebug('[DEBUG PATH] ' + newDep + ' is in ' + deppath, VERBOSE)
							stop = exploreDependenciesTreeDFS(path, cFilePath, destFolder, deps=deps+[deppath])
							if stop:
								return True
						else:
							printAndSave('ERROR,' + cFilePath + ':' + deppath + ',' + 'Missing ' + missingHeader + ',', destFolder + LOG_FILENAME, SAVE_LOGS, PRINT_LOGS)
		return preprocAndStop(cFilePath, deps, 0, destFolder)
	else:
		printAndSave('ERROR,' + cFilePath + ',' + 'Missing ' + missingHeader + ',', destFolder + LOG_FILENAME, SAVE_LOGS, PRINT_LOGS)
		
	
	
	
def exploreDepsAndPreproc(path, filepath, deps=list()):
	deplist = getDependencies(filepath, deps=deps)
	pathlist = []
	for dep in deplist:
		libpaths = glob.glob(path + '**/' + dep, recursive=True)
		onlylibpaths = [keepDependencyPath(libpath, dep) for libpath in libpaths]
		pathlist.append(onlylibpaths)
	pathlist = removeEmptySublists(getAllCombinations(removeDuplicates(pathlist)))
	tmplist = []
	for i in range(len(pathlist)):
		new_combos = exploreDependenciesTreeBFS(path, filepath, deps=deps+pathlist[i])
#		print('+++ ', new_combos)
		if len(new_combos) > 0:
			for combo in new_combos:
				tmplist.append(pathlist[i] + combo)
		else:
			tmplist.append(pathlist[i])
			stop = preprocAndStop(filepath, tmplist[-1], i)
			if stop:
				break	



#def findMissingDependency(err_decoded):
#	if re.search('#include\s+<', err_decoded):
#		return re.split('#include\s+<', err_decoded.strip())[1].split('>')[0]
#	elif re.search('#include\s+"', err_decoded):
#		return re.split('#include\s+"', err_decoded.strip())[1].split('"')[0]
#	else:
#		print('[DEBUG] Could not find the library name')
##		print(err_decoded)
#		sys.exit(-1)



def getDependencies(filepath, deps=list()):
	cmdList = ['cpp', '-M', '-MG', filepath]
	for dep in deps:
		cmdList.append('-I')
		cmdList.append(dep)
	printDebug('[DEBUG] Dependencies: ' + ' '.join(cmdList), VERBOSE)
	proc = subprocess.Popen(cmdList, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	out, _ = proc.communicate()
	deplist = out.decode('utf-8', errors='ignore').replace('\n', '').replace(' \ ', ' ').split(': ')[1].replace('\ ', '[space_tag]').split(' ')
	deplist = cleanDependencies(deplist, filepath)
#	print('===>', deplist)
	return deplist
	
	
	
	
def preprocAndStop(cFile, includes, include_id, destFolder):
	outFile = HOME_DIR + PREPROC_DIR + cFile.replace('../', '')[:-2] + '_' + str(include_id) + '.i'
	errFile = HOME_DIR + PREPROC_DIR + cFile.replace('../', '')[:-2] + '_' + str(include_id) + '.err'
	#includes = sorted(includes) # Sort paths in alphabetical order for reproducibility
	includes = [inc for inc in includes]
	cmdList = ['cpp', cFile]
	for inc in includes:
		cmdList += ['-I', inc]
	start_time = time.time()
	with open(outFile, 'w') as fout:
		with open(errFile, 'w') as ferr:
			subprocess.run(cmdList, stdout=fout, stderr=ferr)
	preproc_time = time.time() - start_time
	if os.stat(errFile).st_size > 0:
		with open(errFile, 'r') as f:
			if '#include' in f.read():
#				printAndSave('ERROR,' + cFile + ',' + ' '.join(cmdList) + ',' + str(preproc_time), destFolder + LOG_FILENAME, SAVE_LOGS, PRINT_LOGS) #could not be preprocessed: missing libs
				printDebug('[DEBUG] Removing ' + outFile + ' and ' + errFile, VERBOSE)
				os.remove(outFile)
				os.remove(errFile)
				return False # Preprocessing failed, keep going
			else:
				printAndSave('WARNING,' + cFile + ',' + ' '.join(cmdList) + ',' + str(preproc_time), destFolder + LOG_FILENAME, SAVE_LOGS, PRINT_LOGS) #nothing else to include: check the error file
				return True # Preprocessing completed (with warning), stop
	else:
		printAndSave('COMPLETED,' + cFile + ',' + ' '.join(cmdList) + ',' + str(preproc_time), destFolder + LOG_FILENAME, SAVE_LOGS, PRINT_LOGS)
		printDebug('[DEBUG] Removing ' + errFile, VERBOSE)
		os.remove(errFile)
		return True # Preprocessing completed, stop
	
	


def tic():
	global stime
	stime=time.time()

def toc(name=""):
	print(name,time.time()-stime)

def getAllProjectHeader(prjPath):
	dep=subprocess.check_output(["find",prjPath,"-type","f","-name","*.h"],universal_newlines=True)
	dep=dep.split("\n")[0:-2]
	dep=[str(Path(d).parent) for d in dep]+["/usr/include","/usr/local/include","/opt/include","/usr/include/X11","/usr/include/asm",
		"/usr/include/linux","usr/include/ncurses"]
	return list(set(dep))

if __name__ == '__main__':
	start_time = time.time()
	checkNumberInputs(sys.argv)
	path, cFiles = getInputs(sys.argv)
	destFolder = HOME_DIR + PREPROC_DIR + path.replace('../', '')
	project_name_bar = path.replace('../', '').replace('__XOXO__', '/')
	try:
		shutil.copytree(path, destFolder, ignore=ignore_files, symlinks=True)
	except FileExistsError:
		print('The folder ' + destFolder + ' already exists, delete or rename it')
		sys.exit(-1)
	os.system('chmod -R 777 ' + destFolder) # shutil.copytree copies also folder permissions
	
	total = len(cFiles)
	for iteration, cFile in enumerate(cFiles):
		#tic()
		printDebug('########################################', VERBOSE)
		printDebug('[DEBUG] Filename ('+str(iteration+1)+'/'+str(total)+'): ' + cFile, VERBOSE)
		exploreDependenciesTreeDFS(path, cFile, destFolder,deps=getAllProjectHeader(path))
		#toc()
		if not VERBOSE and not PRINT_LOGS:
			printProgressBar(iteration+1, total, prefix='Preprocessing', suffix=project_name_bar, length=50)
	end_time = time.time()
	printAndSave('-------------', destFolder + LOG_FILENAME, SAVE_LOGS, PRINT_LOGS)
	printAndSave('TIME\t' + str(end_time - start_time) + ' seconds', destFolder + LOG_FILENAME, SAVE_LOGS, PRINT_LOGS)