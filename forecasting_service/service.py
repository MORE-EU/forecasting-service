import os

from sail.models.auto_ml.auto_pipeline import SAILAutoPipeline
from sail.pipeline import SAILPipeline

from forecasting_service.base import BaseService
from forecasting_service.parser import param_parser, flatten_list


class ForecastingService(BaseService):
    def __init__(self, modelardb_conn, message_broker, logging_level, data_dir) -> None:
        super(ForecastingService, self).__init__(
            self.__class__.__name__,
            modelardb_conn,
            message_broker,
            logging_level,
            data_dir,
        )

    def load_or_create_model(self, configs):
        if configs["model_path"]:
            model = SAILAutoPipeline.load_model(configs["model_path"])
            self.logger.info(
                f"SAILAutoPipeline loaded successfully from - [{configs['model_path']}]."
            )
        else:
            model = self.create_model_instance(configs)
            self.logger.info("SAILAutoPipeline created successfully.")

        return model

    def create_model_instance(self, configs):
        sail_auto_pipeline_params = {}

        sail_auto_pipeline_params["pipeline"] = SAILPipeline(
            **flatten_list(param_parser(configs["sail_pipeline"]))
        )

        sail_auto_pipeline_params["pipeline_params_grid"] = [
            flatten_list(grid) for grid in param_parser(configs["parameter_grid"])
        ]

        sail_auto_pipeline_params["search_method"] = configs["search_method"]
        sail_auto_pipeline_params["search_method_params"] = flatten_list(
            param_parser(configs["search_method_params"])
        )
        sail_auto_pipeline_params["search_data_size"] = configs["search_data_size"]
        sail_auto_pipeline_params["incremental_training"] = configs[
            "incremental_training"
        ]
        sail_auto_pipeline_params["pipeline_strategy"] = configs["pipeline_strategy"]
        sail_auto_pipeline_params["drift_detector"] = param_parser(
            configs["drift_detector"]
        )

        return SAILAutoPipeline(**sail_auto_pipeline_params)

    def process_ts_batch(self, model, ts_batch, target, timestamp_col, fit_params):
        if not super(ForecastingService, self).process_ts_batch(
            ts_batch, timestamp_col
        ):
            return False

        time_stamps = ts_batch[timestamp_col]
        X = ts_batch.drop([target, timestamp_col], axis=1)
        y = ts_batch[target]

        predictions = {}
        if model.best_pipeline:
            preds = model.predict(X)
            for time, pred in zip(time_stamps, preds):
                predictions[str(time)] = pred

        model.train(X, y, **fit_params)

        return predictions

    def send_response(self, json_message):
        super(ForecastingService, self).send_response(json_message)

    def log_state(self):
        super(ForecastingService, self).log_state()

    def run(self):
        super(ForecastingService, self).run()
        # self.risk_msg_thread = threading.Thread(
        #     target=self.run_forever, args=(,)
        # )
        # self.risk_msg_thread.start()
        # self.risk_msg_thread.join()
        self.run_forever(self.process_time_series)
