import json
import sys

import serving.forecasting_pb2 as forecasting_pb2
import serving.forecasting_pb2_grpc as forecasting_pb2_grpc
from google.protobuf.json_format import MessageToDict, ParseDict

import grpc

def get_state(stub):
    response = stub.GetProgress(
        ParseDict(
            {"id": "get_state"},
            forecasting_pb2.JobID(),
        )
    )

    message = MessageToDict(response)
    state = json.loads(message["data"]["state"])

    for job_id, target_dict in state.items():
        for target, target_data in target_dict.items():
            del target_data["run_configs"]

    print(f"Received message - {json.dumps(state, indent=2)}")

def start_training(stub):
    response = stub.StartTraining(
        ParseDict(
            {
                "id": "1345667",
                "config": json.dumps(
                    {
                        "startDate": 1536451202000,
                        "endDate": 1536453200000,
                        "time_interval": "2S",
                        "targetColumn": ["active_power"],
                        "experiment": "WIND_POWER_ESTIMATION",
                    }
                ),
            },
            forecasting_pb2.TrainingInfo(),
        )
    )

    print(f"Received message - {MessageToDict(response)}")


def get_progress(stub):
    response = stub.GetProgress(
        ParseDict(
            {"id": "1345667"},
            forecasting_pb2.JobID(),
        )
    )

    print(f"Received message - {MessageToDict(response)}")


def get_specific_results(stub):
    response = stub.GetSpecificTargetResults(
        ParseDict(
            {"id": "1345667", "name": "active_power"},
            forecasting_pb2.Target(),
        )
    )

    print(f"Received message - {MessageToDict(response)}")


def get_all_results(stub):
    response = stub.GetAllTargetsResults(
        ParseDict(
            {"id": "1345667"},
            forecasting_pb2.JobID(),
        )
    )

    print(f"Received message - {MessageToDict(response)}")

def save_model(stub):
    response = stub.SaveModel(
        ParseDict(
            {"model_type": "SAIL_AutoML", "model_name": "SAILModel", "target": "active_power"},
            forecasting_pb2.ModelInfo(),
        )
    )

    print(f"Received message - {MessageToDict(response)}")


def get_inference(stub):
    response = stub.GetInference(
        ParseDict(
            {"timestamp": 1536453200000, "model_name": "SAILModel"},
            forecasting_pb2.Timestamp(),
        )
    )

    print(f"Received message - {MessageToDict(response)}")

def get_models(stub):
    response = stub.GetModels(
        ParseDict(
            {},
            forecasting_pb2.EmptyRequest(),
        )
    )

    print(f"Received message - {MessageToDict(response)}")

def delete_models(stub):
    response = stub.DeleteModel(
        ParseDict(
            {"modelName": "SAILModel"},
            forecasting_pb2.ModelName(),
        )
    )

    print(f"Received message - {MessageToDict(response)}")


def run(service):
    # NOTE(gRPC Python Team): .close() is possible on a channel and should be
    # used in circumstances in which the with statement does not fit the needs
    # of the code.
    with grpc.insecure_channel("localhost:50051") as channel:
        stub = forecasting_pb2_grpc.RouteGuideStub(channel)

        if service == "state":
            print("-------------- GRPC_STATE --------------")
            get_state(stub)
        elif service == "training":
            print("-------------- StartTraining --------------")
            start_training(stub)
        elif service == "progress":
            print("-------------- GetProgress --------------")
            get_progress(stub)
        elif service == "specific_results":
            print("-------------- GetSpecificTargetResults --------------")
            get_all_results(stub)
        elif service == "all_results":
            print("-------------- GetAllTargetsResults --------------")
            get_all_results(stub)
        elif service == "save":
            print("-------------- SaveModel --------------")
            save_model(stub)
        elif service == "inference":
            print("-------------- GetInference --------------")
            get_inference(stub)
        elif service == "get_models":
            print("-------------- SaveModel --------------")
            get_models(stub)
        elif service == "delete_model":
            print("-------------- GetInference --------------")
            delete_models(stub)
        else:
            print("-------------- Error: Invalid service name. --------------")


if __name__ == "__main__":
    run(sys.argv[1])
