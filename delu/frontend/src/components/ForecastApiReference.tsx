import SwaggerUI from "swagger-ui-react";
import "swagger-ui-react/swagger-ui.css";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import "./forecast-api-reference.css";

export default function ForecastApiReference() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Forecast API reference</CardTitle>
        <CardDescription>
          Authorize with your key, open GET /v1/forecast, set the inputs, and select Execute.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="forecast-api-reference overflow-hidden rounded-lg border border-line">
          <SwaggerUI
            url="/openapi-forecast.json"
            docExpansion="list"
            defaultModelsExpandDepth={-1}
            tryItOutEnabled
            persistAuthorization
          />
        </div>
      </CardContent>
    </Card>
  );
}
