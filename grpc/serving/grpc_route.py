import json
import os
import threading
from datetime import datetime
import shutil
import numpy as np
import serving.forecasting_pb2 as forecasting_pb2
import serving.forecasting_pb2_grpc as forecasting_pb2_grpc
import yaml
from more_utils.logging import configure_logger

from grpc import StatusCode

LOGGER = configure_logger(logger_name="GRPC_Server", package_name=None)

EXPERIMENT_TO_CONFIG_FILE = {
    "WIND_POWER_ESTIMATION": "regression_wind_power_estimation.yaml"
}

# Define a shared variable to hold the object returned from the background task
shared_lock = threading.Lock()


class ServerMessageHandler:
    def __init__(self):
        self.message = None

    def handler(self, message):
        self.message = json.loads(message)


class RouteGuideServicer(forecasting_pb2_grpc.RouteGuideServicer):
    def __init__(self, rabbitmq_context, data_dir, config_dir):
        self.jobs = {}
        self.rabbitmq_context = rabbitmq_context
        self.data_dir = data_dir
        self.config_dir = config_dir

    def process_reponse(self):
        with self.rabbitmq_context.client() as client:
            receiver = client.get_consumer()
            while True:
                message = receiver.receive(
                    handler=ServerMessageHandler().handler, max_messages=1, timeout=None
                )
                message = message.decode("UTF-8")
                message = json.loads(message)

                with shared_lock:
                    job_id = message["job_id"]
                    if job_id in self.jobs:
                        target = message["target"]
                        LOGGER.info(
                            f"Message Received: {message} for job_id: {job_id} and target: {target}"
                        )
                        target_data = self.jobs[job_id][target]
                        msg_response = {
                            "timestamp": message["timestamp"],
                            "service": message["service"],
                            "task": message["experiment"],
                            "response": message["response"],
                        }

                        if target_data["status"] == "inference":
                            target_data["inference"] = msg_response
                        else:
                            target_data.update(msg_response)

                        if "COMPLETED" == message["status"]:
                            target_data["status"] = "done"

                    else:
                        LOGGER.error(f"Invalid Job Id received. Message: {message}")

    def get_state(self, job_id):
        return forecasting_pb2.Progress(
            id=job_id, data={"state": json.dumps(self.jobs)}
        )

    def StartTraining(self, request, context):
        LOGGER.info(f"[StartTraining] - Request received with job id:{request.id}.")

        # Read the config from the request
        configs = json.loads(request.config)

        # for each target column, create a status with waiting
        self.jobs[request.id] = {}
        for target in configs["targetColumn"]:
            self.jobs[request.id] = {target: {"status": "waiting"}}

            with open(
                os.path.join(
                    self.config_dir, EXPERIMENT_TO_CONFIG_FILE[configs["experiment"]]
                )
            ) as fp:
                run_configs = yaml.safe_load(fp)

            # append parameters
            run_configs["job_id"] = request.id
            run_configs["data_stream"]["target"] = target
            run_configs["data_stream"]["time_interval"] = configs["time_interval"]
            run_configs["data_stream"]["from_date"] = str(
                datetime.fromtimestamp(configs["startDate"] / 1000)
            )
            run_configs["data_stream"]["to_date"] = str(
                datetime.fromtimestamp(configs["endDate"] / 1000)
            )

            with self.rabbitmq_context.client() as client:
                publisher = client.get_publisher()
                publisher.publish(json.dumps(run_configs))

            self.jobs[request.id][target]["status"] = "processing"
            self.jobs[request.id][target]["run_configs"] = run_configs

        return forecasting_pb2.Status(id=request.id, status="started")

    def GetProgress(self, request, context):
        """
        Get progress for a specific job
        Return: The job id and the status of each target column
        """
        job_id = request.id

        if job_id == "get_state":
            return self.get_state(job_id)
        else:
            if job_id in self.jobs:
                # Create a Struct message
                data = {}

                # Add the status of each target column to the struct
                for target, target_data in self.jobs[job_id].items():
                    data[target] = target_data["status"]

                return forecasting_pb2.Progress(id=job_id, data=data)
            else:
                # return empty response
                context.abort(StatusCode.INVALID_ARGUMENT, "Not a valid job id")

    def GetSpecificTargetResults(self, request, context):
        """
        Get the results for a specific target column
        Return: The predictions and evaluation metrics for each model
        """
        target = request.name
        job_id = request.id

        if job_id in self.jobs:
            if target in self.jobs[job_id]:
                target_data = self.jobs[job_id][target]
                if target_data["status"] == "done":
                    data = {}
                    # assign the prediction results for each model
                    data["SAILModel"] = forecasting_pb2.Predictions(
                        predictions=self.get_predictions(target_data),
                        evaluation=self.get_evaluation(target_data),
                    )

                    return forecasting_pb2.Results(target=target, metrics=data)
                else:
                    # return empty response
                    context.abort(
                        StatusCode.INVALID_ARGUMENT, "Task has not finished yet"
                    )
        else:
            # return empty response
            context.abort(
                StatusCode.INVALID_ARGUMENT, "Not a valid job id or target column"
            )

    def GetAllTargetsResults(self, request, context):
        """
        Get the results for all target columns
        Return: The predictions and evaluation metrics for each model for each target column
        """
        job_id = request.id
        # create an empty response - array of dictionaries where each dictionary is a target column
        all_results = forecasting_pb2.AllResults()

        if job_id in self.jobs:
            data = {}
            for target, target_data in self.jobs[job_id].items():
                data[target] = {}

                if target_data["status"] == "done":
                    data[target]["SAILModel"] = forecasting_pb2.Predictions(
                        predictions=self.get_predictions(target_data),
                        evaluation=self.get_evaluation(target_data),
                    )

                # add the target column and its results to the response
                all_results.results.append(
                    forecasting_pb2.Results(target=target, metrics=data[target])
                )
            return all_results
        else:
            # return empty response
            context.abort(StatusCode.INVALID_ARGUMENT, "Not a valid job id")

    def get_predictions(self, target_data):
        service = target_data["service"]
        task_name = target_data["task"]

        with open(
            os.path.join(self.data_dir, service, task_name, "response.json")
        ) as output:
            response = json.load(output)
            predictions = {
                timestamp: float(value)
                for timestamp, value in response["predictions"].items()
            }
            return predictions

    def get_evaluation(self, target_data):
        service = target_data["service"]
        task_name = target_data["task"]

        with open(
            os.path.join(self.data_dir, service, task_name, "evaluation.json")
        ) as output:
            response = json.load(output)
            return response["evaluation"]

    def SaveModel(self, request, context):
        # get the information
        model_type = request.model_type
        model_name = request.model_name
        target_req = request.target

        for job_id, target_dict in self.jobs.items():
            # verify that target exist in trainers
            for target, target_data in target_dict.items():
                if target == target_req:
                    status = target_data["status"]
                    if status == "done":
                        shutil.move(
                            os.path.join(
                                self.data_dir,
                                target_data["service"],
                                target_data["task"],
                                target_data.pop("model", "model"),
                            ),
                            os.path.join(
                                self.data_dir,
                                target_data["service"],
                                target_data["task"],
                                model_name,
                            ),
                        ),
                        target_data["model"] = model_name
                    return forecasting_pb2.Status(id=job_id, status=status)

        # return empty response
        context.abort(
            StatusCode.INVALID_ARGUMENT,
            "Task has not finished yet or not exists",
        )

    def GetInference(self, request, context):
        # get the timestamp from the request and convert it to a datetime object
        date = datetime.fromtimestamp(request.timestamp / 1000)
        model_name = request.model_name

        y_pred = None
        for target_dict in self.jobs.values():
            for target_data in target_dict.values():
                if (
                    target_data["status"] == "done"
                    and "model" in target_data
                    and target_data["model"] == model_name
                ):
                    run_configs = target_data["run_configs"]
                    run_configs["sail"]["model_path"] = os.path.join(
                        "/data",
                        target_data["task"],
                        target_data["model"],
                    )
                    run_configs["data_stream"]["from_date"] = str(date)
                    run_configs["data_stream"]["to_date"] = None
                    run_configs["data_stream"]["data_limit"] = run_configs[
                        "data_stream"
                    ]["data_batch_size"]

                    with self.rabbitmq_context.client() as client:
                        publisher = client.get_publisher()
                        publisher.publish(json.dumps(run_configs))
                        target_data["status"] = "inference"

                        while True:
                            if target_data["status"] == "done":
                                y_pred = self.get_predictions(target_data["inference"])
                                break

        if y_pred is None:
            # return empty response if model not exist
            context.abort(
                StatusCode.INVALID_ARGUMENT,
                "Model does not exist. Training still in progress or you did not call SaveModel.",
            )
        else:
            return forecasting_pb2.Inference(predictions=y_pred)

    def GetModels(self, request, context):
        models = []
        for job_id, target_dict in self.jobs.items():
            for target, target_data in target_dict.items():
                if "model" in target_data:
                    models.append(target_data["model"])
        
        return forecasting_pb2.Models(models=models)

    def DeleteModel(self, request, context):
        # get the information
        model_name = request.modelName

        model_deleted = 0
        for job_id, target_dict in self.jobs.items():
            for target, target_data in target_dict.items():
                if "model" in target_data and model_name == target_data["model"]:
                    del target_data["model"]
                    model_deleted += 1
        
        if model_deleted > 0:
            return forecasting_pb2.Report(report="success")
        else:
            return forecasting_pb2.Report(report="error")