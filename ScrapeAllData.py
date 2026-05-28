import json
import time
import os
import pandas as pd
from copy import deepcopy
from typing import Dict, Tuple, List, Union
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from tqdm import tqdm, trange

from Helper.ProcessDeviceName import CPUName, GPUName
from Helper.Get3DMarkScore import (
    GetNameFromId,
    GetMedianScoreFromId,
    CPU_TESTSCENE,
    GPU_TESTSCENE,
    TESTSCENE_TYPE,
)

DATA_TYPE = Dict[int, Dict[str, Union[int, str]]]
DIST_DIR = "/workspace/dist"


def GetAllDeviceInfo(
    IsCpu: bool, TestSceneList: List[TESTSCENE_TYPE], *Args: int
) -> DATA_TYPE:
    IdToDeviceInfo: DATA_TYPE
    DEVICE: str = "CPU" if IsCpu else "GPU"
    MinId: int = 1
    MaxId: int = 4000 if IsCpu else 2000
    if len(Args) > 0:
        MinId = Args[0]
    if len(Args) > 1:
        MaxId = Args[1]

    with ThreadPoolExecutor(max_workers=os.cpu_count()) as ThreadPool:
        print("------------------------------------------")
        print(f"Get {DEVICE} Name From ID ({MinId} To {MaxId})")
        Threads: List[Future] = []
        Threads.extend(
            ThreadPool.submit(GetNameFromId, i, IsCpu)
            for i in trange(MinId, MaxId + 1, desc="Tasks Submitting...", unit="tasks")
        )

        IdToDeviceInfo = {}
        with tqdm(
            as_completed(Threads),
            total=MaxId - MinId + 1,
            desc="Tasks Executing...",
            unit="tasks",
        ) as ProgressBar:
            for Thread in ProgressBar:
                try:
                    Result: Tuple[int, str] = Thread.result()
                    if Result[1] != "":
                        Id: int = Result[0]
                        Name: str = Result[1]

                        Item = {
                            f"{DEVICE} ID": Id,
                            f"{DEVICE} Name": Name,
                        }
                        for TestScene in TestSceneList:
                            Item[TestScene.value[2]] = -1

                        IdToDeviceInfo[Id] = Item

                        ProgressBar.set_description_str(
                            f"Tasks Executing... Current {DEVICE}:{Name:^35}"
                        )
                except Exception as e:
                    print(f"====== An Exception Raised! ======\n{e}")

        def GetScore(TestScene: TESTSCENE_TYPE) -> None:
            Threads.clear()
            Threads.extend(
                ThreadPool.submit(GetMedianScoreFromId, TestScene, i)
                for i in tqdm(
                    IdToDeviceInfo.keys(), desc="Tasks Submitting...", unit="tasks"
                )
            )

            with tqdm(
                as_completed(Threads),
                total=len(Threads),
                desc="Tasks Executing...",
                unit="tasks",
            ) as ProgressBar:
                for Thread in ProgressBar:
                    try:
                        Result: Tuple[int, int] = Thread.result()
                        Id: int = Result[0]
                        MedianScore: int = Result[1]

                        IdToDeviceInfo[Id][TestScene.value[2]] = MedianScore

                        CurrentDeviceName = IdToDeviceInfo[Result[0]][f"{DEVICE} Name"]
                        ProgressBar.set_description_str(
                            f"Tasks Executing... Current {DEVICE}:{CurrentDeviceName:^35}, Current Score:{MedianScore:^10}"
                        )
                    except Exception as e:
                        print(f"====== An Exception Raised! ======\n{e}")

        for TestScene in TestSceneList:
            print("------------------------------------------")
            print(f"Get {TestScene.value[2]}")
            GetScore(TestScene)

    return IdToDeviceInfo


def ProcessData(Data: DATA_TYPE, IsCpu: bool, OutputDir: str) -> None:
    if len(Data) == 0:
        return

    Df = pd.DataFrame(Data.values())

    COL_NAME = "CPU Name" if IsCpu else "GPU Name"
    COL_NAME_GUID = f"{COL_NAME} GUID"
    COL_ID = "CPU ID" if IsCpu else "GPU ID"
    COL_VENDOR = "Vendor"
    COL_MODEL = "Model"
    COL_SCORES = [Column for Column in Df.columns if "3DMark" in Column]
    assert len(COL_SCORES) != 0
    COL_MAINSCORE = COL_SCORES[0]
    SCORE_LIMIT = 1
    GUID_CLASS = CPUName if IsCpu else GPUName

    Df = Df[Df[COL_NAME] != ""]
    Df[COL_ID] = Df[COL_ID].astype(int)

    Df[COL_MAINSCORE] = Df[COL_MAINSCORE].astype(int)
    Df = Df[Df[COL_MAINSCORE] >= SCORE_LIMIT]
    Df[COL_NAME_GUID] = Df[COL_NAME].apply(GUID_CLASS)
    VendorSeries = Df[COL_NAME_GUID].apply(lambda Obj: Obj.Vendor)
    Df.insert(Df.columns.get_loc(COL_NAME), COL_VENDOR, VendorSeries)
    ModelSeries = Df[COL_NAME_GUID].apply(lambda Obj: Obj.Model)
    Df.insert(Df.columns.get_loc(COL_NAME), COL_MODEL, ModelSeries)
    Df.sort_values(COL_MAINSCORE, ascending=False, inplace=True)
    Df.reset_index(drop=True, inplace=True)

    ExcelPath = os.path.join(OutputDir, f"3DMark_{'CPU' if IsCpu else 'GPU'}ScoreData.xlsx")
    with pd.ExcelWriter(ExcelPath, engine="openpyxl") as w:
        Df.to_excel(w, sheet_name="Sheet1", index=False)

    print(f"Excel saved to: {ExcelPath}")
    print(Df)


def Main() -> None:
    os.makedirs(DIST_DIR, exist_ok=True)

    print("=" * 60)
    print("开始抓取所有 3DMark 数据")
    print("=" * 60)

    all_test_scenes = list(CPU_TESTSCENE)
    print("\n抓取 CPU 数据...")
    print(f"测试项目: {[t.value[2] for t in all_test_scenes]}")
    
    StartTime = time.time()
    CpuData = GetAllDeviceInfo(True, all_test_scenes)
    print(f"\nCPU 数据抓取完成，耗时: {time.time() - StartTime:.2f}s")

    CpuJsonPath = os.path.join(DIST_DIR, f"CPU_{'_'.join([t.name for t in all_test_scenes])}.json")
    with open(CpuJsonPath, "w", encoding="utf-8") as File:
        json.dump(CpuData, File)
    print(f"CPU JSON 保存到: {CpuJsonPath}")

    ProcessData(CpuData, True, DIST_DIR)

    all_test_scenes = list(GPU_TESTSCENE)
    print("\n" + "=" * 60)
    print("抓取 GPU 数据...")
    print(f"测试项目: {[t.value[2] for t in all_test_scenes]}")
    
    StartTime = time.time()
    GpuData = GetAllDeviceInfo(False, all_test_scenes)
    print(f"\nGPU 数据抓取完成，耗时: {time.time() - StartTime:.2f}s")

    GpuJsonPath = os.path.join(DIST_DIR, f"GPU_{'_'.join([t.name for t in all_test_scenes])}.json")
    with open(GpuJsonPath, "w", encoding="utf-8") as File:
        json.dump(GpuData, File)
    print(f"GPU JSON 保存到: {GpuJsonPath}")

    ProcessData(GpuData, False, DIST_DIR)

    print("\n" + "=" * 60)
    print("所有数据抓取完成！")
    print(f"输出目录: {DIST_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    Main()
