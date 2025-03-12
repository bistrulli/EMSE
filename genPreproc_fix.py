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
    # Verify that the first parameter is a directory.
    if not os.path.isdir(params[1]):
        # Print an error message and exit if the first parameter is not a valid directory.
        print('The first parameter must be a directory')
        sys.exit(-1)
    else:
        # Ensure the directory path ends with a '/'.
        if params[1][-1] != '/':
            path = params[1] + '/'
        else:
            path = params[1]
            
    # Check if a second parameter is provided.
    if len(params) == 3:
        # Verify that the second parameter is either a directory or a file.
        if not (os.path.isdir(params[2]) or os.path.isfile(params[2])):
            print('If provided, the second parameter must be a file or a directory')
            sys.exit(-1)
        elif os.path.isfile(params[2]):
            # If it's a file, ensure it is a C file by checking its extension.
            if params[2][-2:] == '.c':
                cFiles = [params[2]]
            else:
                print('If the second parameter is a file, then it must be a C file')
                sys.exit(-1)
        else:
            # If the second parameter is a directory, check if the path ends with '/'.
            if params[2][-1] != '/':
                # Use 'find' to search for .c files in the provided directory.
                proc = subprocess.Popen(['find', params[2], '-name', '*.c'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                cFiles, _ = proc.communicate()
                cFiles = cFiles.decode('utf-8', errors='ignore').split('\n')
                if cFiles[-1] == '':
                    cFiles = cFiles[:-1]
            else:
                # If the directory path ends with '/', use a similar 'find' command.
                proc = subprocess.Popen(['find', params[2] + '/', '-name', '*.c'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                cFiles, _ = proc.communicate()
                cFiles = cFiles.decode('utf-8', errors='ignore').split('\n')
                if cFiles[-1] == '':
                    cFiles = cFiles[:-1]
    else:
        # If no second parameter is provided, search for .c files in the main directory.
        proc = subprocess.Popen(['find', path, '-name', '*.c'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        cFiles, _ = proc.communicate()
        cFiles = cFiles.decode('utf-8', errors='ignore').split('\n')
        if cFiles[-1] == '':
            cFiles = cFiles[:-1]
    # Return the main directory path and the list of C files after removing symlinks.
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
    # Retrieve the list of headers required by the file using getDependencies.
    headers = getDependencies(filepath)
    for header in headers:
        # Replace placeholder for space with an actual space.
        header = header.replace('[space_tag]', ' ')
        # Search for the header file within the directory tree.
        headerpaths = glob.glob(path + '**/' + header, recursive=True)
        # Remove any paths that are symbolic links or directories.
        headerpaths = removeIfLink(headerpaths)
        # If no valid header file is found, return False with the missing header name.
        if len(headerpaths) == 0:
            return False, header
    # If all headers are found, return True and None for the missing header.
    return True, None

def parseDependencyError(err_decoded):
    """
    Refactored function to parse the missing dependency from a cpp error message.
    It returns the name of the missing header.
    """
    import re
    err_decoded = err_decoded.strip()
    # Try to match user-defined includes ("header.h") or system includes (<header.h>).
    match = re.search(r'#include\s+[<"]([^">]+)[">]', err_decoded)
    if match:
        return match.group(1)
    else:
        print('[DEBUG] Could not find the library name in:', err_decoded)
        sys.exit(-1)

def exploreDependenciesTreeDFS(path, cFilePath, destFolder, deps=list()):
    # Check if the initial dependencies are provided. If not, verify if the cFile has all required headers.
    keepGoing = True
    if len(deps) == 0:
        # If deps is empty, check if cFilePath contains all necessary headers.
        keepGoing, missingHeader = allHeadersExist(cFilePath)
    if keepGoing:
        # Build the command list for invoking the 'cpp' preprocessor.
        cmdList = ['cpp', '-M', cFilePath]
        for dep in deps:
            # Append each dependency as a -I parameter to include the specified paths.
            cmdList += ['-I', dep]
        # Debug: Display the command parameters passed to cpp.
        printDebug('[DEBUG] Dependencies: ' + ' '.join(cmdList), VERBOSE)
        proc = subprocess.Popen(cmdList, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _, err = proc.communicate()
        errStr = err.decode('utf-8', errors='ignore')
        if '#include' in errStr:
            # If cpp reports problems with #include directives, analyze each line of the error output.
            for line in errStr.split('\n'):
                if '#include' in line:
                    deppaths = None
                    if '"' in line:
                        # Case: user-defined include (quotes).
                        newDep = line.split('"')[1]
                        filepath = '/'.join(cFilePath.split('/')[:-1])
                        # In this example, you may look for the corresponding path.
                        deppaths = []
                    if deppaths is None:
                        # Case: system include (angles), extract the library name.
                        if '<' in line:
                            newDep = line.split('<')[1].split('>')[0]
                        deppaths = []
                    elif len(deppaths) == 0:
                        # No path found for the new include.
                        pass
                    # Clean invalid paths (e.g., symbolic links).
                    deppaths = removeIfLink(deppaths)
                    for deppath in deppaths:
                        # Check if the found path contains all required headers.
                        keepGoing, missingHeader = allHeadersExist(deppath)
                        if keepGoing:
                            # Remove the new header name from the string to obtain just the path.
                            deppath = deppath[:-len(newDep)]
                            # Debug: Report in which path the header was found.
                            printDebug('[DEBUG PATH] ' + newDep + ' is in ' + deppath, VERBOSE)
                            # Recursively call the function, adding the new path to the dependencies.
                            stop = exploreDependenciesTreeDFS(path, cFilePath, destFolder, deps=deps+[deppath])
                            if stop:
                                return True
                        else:
                            # If a header is missing, log the error.
                            printAndSave('ERROR,' + cFilePath + ':' + deppath + ',' + 'Missing ' + missingHeader + ',', destFolder + LOG_FILENAME, SAVE_LOGS, PRINT_LOGS)
        # Finally, perform the actual preprocessing and stop further exploration.
        return preprocAndStop(cFilePath, deps, 0, destFolder)
    else:
        # If not all headers are present, log the error and exit the function.
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
    # Execute a 'find' command to locate all .h files in the given project directory.
    dep = subprocess.check_output(["find", prjPath, "-type", "f", "-name", "*.h"], universal_newlines=True)
    # Split the output by newline and remove the last two entries (typically empty lines).
    dep = dep.split("\n")[0:-2]
    # Convert each header file path to its parent directory and append common system include directories.
    dep = [str(Path(d).parent) for d in dep] + ["/usr/include", "/usr/local/include", "/opt/include", "/usr/include/X11", "/usr/include/asm",
                                               "/usr/include/linux", "usr/include/ncurses"]
    # Remove duplicate entries by converting the list to a set, then return as a list.
    return list(set(dep))

if __name__ == '__main__':
    # Start the timer to measure the total execution time.
    start_time = time.time()
    # Verify that the number and type of input parameters are correct.
    checkNumberInputs(sys.argv)
    # Extract the main directory path and the list of .c files to process.
    path, cFiles = getInputs(sys.argv)
    # Construct the destination directory path for preprocessed files.
    destFolder = HOME_DIR + PREPROC_DIR + path.replace('../', '')
    # Prepare a project identifier string for the progress bar.
    project_name_bar = path.replace('../', '').replace('__XOXO__', '/')
    try:
        # Copy the entire directory tree to the destination, preserving symlinks.
        shutil.copytree(path, destFolder, ignore=ignore_files, symlinks=True)
    except FileExistsError:
        # Inform the user if the destination folder already exists and exit.
        print('The folder ' + destFolder + ' already exists, delete or rename it')
        sys.exit(-1)
    # Recursively change the permissions of the destination folder.
    os.system('chmod -R 777 ' + destFolder)

    # Determine the total number of .c files to process.
    total = len(cFiles)
    # Iterate over each .c file.
    for iteration, cFile in enumerate(cFiles):
        # (Optional) Start timing measurement for the current file (currently commented out).
        #tic()
        # Print a debug separator.
        printDebug('########################################', VERBOSE)
        # Display the current file name and processing progress.
        printDebug('[DEBUG] Filename (' + str(iteration + 1) + '/' + str(total) + '): ' + cFile, VERBOSE)
        # Retrieve project header files.
        deps = getAllProjectHeader(path)
        # Process the file's dependencies and start preprocessing with the obtained headers.
        exploreDependenciesTreeDFS(path, cFile, destFolder, deps=deps)
        # (Optional) End timing measurement for the current file (currently commented out).
        #toc()
        # Update the terminal progress bar.
        if not VERBOSE and not PRINT_LOGS:
            printProgressBar(iteration + 1, total, prefix='Preprocessing', suffix=project_name_bar, length=50)
    # Record the end time of the execution.
    end_time = time.time()
    # Append a separator line to the log file.
    printAndSave('-------------', destFolder + LOG_FILENAME, SAVE_LOGS, PRINT_LOGS)
    # Log and save the total execution time.
    printAndSave('TIME\t' + str(end_time - start_time) + ' seconds', destFolder + LOG_FILENAME, SAVE_LOGS, PRINT_LOGS)