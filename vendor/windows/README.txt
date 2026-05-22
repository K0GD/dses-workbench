sdrPlaySupport.dll — pre-built SoapySDR module for SDRplay RSP receivers
========================================================================

What this is
------------
This is Pothosware's SoapySDRPlay3 module, compiled for Windows x64. It is
the bridge between SoapySDR (which the analyzer uses) and the SDRplay API
(the manufacturer's driver). SoapySDRPlay3 is NOT packaged on conda-forge
for any OS, so Windows users cannot `conda install` it — hence we ship this
pre-built binary and the installer copies it into Radioconda's module dir.

Built against
-------------
  SoapySDR ABI:  0.8   (Radioconda's soapysdr 0.8.1; module dir modules0.8)
  SDRplay API:   3.15
  Toolchain:     Visual Studio 2022 (MSVC 19.39), CMake, Release x64
  Source:        https://github.com/pothosware/SoapySDRPlay3

Where it goes on the end user's machine
---------------------------------------
  C:\ProgramData\radioconda\Library\lib\SoapySDR\modules0.8\sdrPlaySupport.dll

(See Installing.md section 1A for the full user-facing steps, including
installing the SDRplay API and starting the SDRplay API service.)

Rebuilding (when Radioconda bumps the SoapySDR ABI past 0.8)
-----------------------------------------------------------
If a future Radioconda ships SoapySDR 0.9+ the module dir becomes
modules0.9 and this 0.8 binary will no longer load. Rebuild per the recipe
in Release_Workflow.md section 7.4, then replace this file.
