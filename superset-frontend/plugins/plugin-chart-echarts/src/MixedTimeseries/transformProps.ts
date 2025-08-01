/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */
/* eslint-disable camelcase */
import { invert } from 'lodash';
import {
  AnnotationLayer,
  AxisType,
  buildCustomFormatters,
  CategoricalColorNamespace,
  CurrencyFormatter,
  ensureIsArray,
  GenericDataType,
  getCustomFormatter,
  getNumberFormatter,
  getXAxisLabel,
  isDefined,
  isEventAnnotationLayer,
  isFormulaAnnotationLayer,
  isIntervalAnnotationLayer,
  isPhysicalColumn,
  isTimeseriesAnnotationLayer,
  QueryFormData,
  QueryFormMetric,
  TimeseriesChartDataResponseResult,
  TimeseriesDataRecord,
  tooltipHtml,
  ValueFormatter,
} from '@superset-ui/core';
import { getOriginalSeries } from '@superset-ui/chart-controls';
import type { EChartsCoreOption } from 'echarts/core';
import type { SeriesOption } from 'echarts';
import {
  DEFAULT_FORM_DATA,
  EchartsMixedTimeseriesChartTransformedProps,
  EchartsMixedTimeseriesFormData,
  EchartsMixedTimeseriesProps,
} from './types';
import {
  EchartsTimeseriesSeriesType,
  ForecastSeriesEnum,
  Refs,
} from '../types';
import { parseAxisBound } from '../utils/controls';
import {
  dedupSeries,
  extractDataTotalValues,
  extractSeries,
  extractShowValueIndexes,
  extractTooltipKeys,
  getAxisType,
  getColtypesMapping,
  getLegendProps,
  getMinAndMaxFromBounds,
  getOverMaxHiddenFormatter,
} from '../utils/series';
import {
  extractAnnotationLabels,
  getAnnotationData,
} from '../utils/annotation';
import {
  extractForecastSeriesContext,
  extractForecastValuesFromTooltipParams,
  formatForecastTooltipSeries,
  rebaseForecastDatum,
  reorderForecastSeries,
} from '../utils/forecast';
import { convertInteger } from '../utils/convertInteger';
import { defaultGrid, defaultYAxis } from '../defaults';
import {
  getPadding,
  transformEventAnnotation,
  transformFormulaAnnotation,
  transformIntervalAnnotation,
  transformSeries,
  transformTimeseriesAnnotation,
} from '../Timeseries/transformers';
import { TIMEGRAIN_TO_TIMESTAMP, TIMESERIES_CONSTANTS } from '../constants';
import { getDefaultTooltip } from '../utils/tooltip';
import {
  getTooltipTimeFormatter,
  getXAxisFormatter,
  getYAxisFormatter,
} from '../utils/formatters';
import { getMetricDisplayName } from '../utils/metricDisplayName';

const getFormatter = (
  customFormatters: Record<string, ValueFormatter>,
  defaultFormatter: ValueFormatter,
  metrics: QueryFormMetric[],
  formatterKey: string,
  forcePercentFormat: boolean,
) => {
  if (forcePercentFormat) {
    return getNumberFormatter(',.0%');
  }
  return (
    getCustomFormatter(customFormatters, metrics, formatterKey) ??
    defaultFormatter
  );
};

export default function transformProps(
  chartProps: EchartsMixedTimeseriesProps,
): EchartsMixedTimeseriesChartTransformedProps {
  const {
    width,
    height,
    formData,
    queriesData,
    hooks,
    filterState,
    datasource,
    theme,
    inContextMenu,
    emitCrossFilters,
  } = chartProps;

  let focusedSeries: string | null = null;

  const {
    verboseMap = {},
    currencyFormats = {},
    columnFormats = {},
  } = datasource;
  const { label_map: labelMap } =
    queriesData[0] as TimeseriesChartDataResponseResult;
  const { label_map: labelMapB } =
    queriesData[1] as TimeseriesChartDataResponseResult;
  const data1 = (queriesData[0].data || []) as TimeseriesDataRecord[];
  const data2 = (queriesData[1].data || []) as TimeseriesDataRecord[];
  const annotationData = getAnnotationData(chartProps);
  const coltypeMapping = {
    ...getColtypesMapping(queriesData[0]),
    ...getColtypesMapping(queriesData[1]),
  };
  const {
    area,
    areaB,
    annotationLayers,
    colorScheme,
    timeShiftColor,
    contributionMode,
    legendOrientation,
    legendType,
    logAxis,
    logAxisSecondary,
    markerEnabled,
    markerEnabledB,
    markerSize,
    markerSizeB,
    opacity,
    opacityB,
    minorSplitLine,
    minorTicks,
    seriesType,
    seriesTypeB,
    showLegend,
    showValue,
    showValueB,
    onlyTotal,
    onlyTotalB,
    stack,
    stackB,
    truncateXAxis,
    truncateYAxis,
    tooltipTimeFormat,
    yAxisFormat,
    currencyFormat,
    yAxisFormatSecondary,
    currencyFormatSecondary,
    xAxisTimeFormat,
    yAxisBounds,
    yAxisBoundsSecondary,
    yAxisIndex,
    yAxisIndexB,
    yAxisTitleSecondary,
    zoomable,
    richTooltip,
    tooltipSortByMetric,
    xAxisBounds,
    xAxisLabelRotation,
    xAxisLabelInterval,
    groupby,
    groupbyB,
    xAxis: xAxisOrig,
    xAxisForceCategorical,
    xAxisTitle,
    yAxisTitle,
    xAxisTitleMargin,
    yAxisTitleMargin,
    yAxisTitlePosition,
    sliceId,
    sortSeriesType,
    sortSeriesTypeB,
    sortSeriesAscending,
    sortSeriesAscendingB,
    timeGrainSqla,
    percentageThreshold,
    showQueryIdentifiers = false,
    metrics = [],
    metricsB = [],
  }: EchartsMixedTimeseriesFormData = { ...DEFAULT_FORM_DATA, ...formData };

  const refs: Refs = {};
  const colorScale = CategoricalColorNamespace.getScale(colorScheme as string);

  let xAxisLabel = getXAxisLabel(
    chartProps.rawFormData as QueryFormData,
  ) as string;
  if (
    isPhysicalColumn(chartProps.rawFormData?.x_axis) &&
    isDefined(verboseMap[xAxisLabel])
  ) {
    xAxisLabel = verboseMap[xAxisLabel];
  }

  const rebasedDataA = rebaseForecastDatum(data1, verboseMap);
  const { totalStackedValues, thresholdValues } = extractDataTotalValues(
    rebasedDataA,
    {
      stack,
      percentageThreshold,
      xAxisCol: xAxisLabel,
    },
  );

  const MetricDisplayNameA = getMetricDisplayName(metrics[0], verboseMap);
  const MetricDisplayNameB = getMetricDisplayName(metricsB[0], verboseMap);

  const [rawSeriesA, sortedTotalValuesA] = extractSeries(rebasedDataA, {
    fillNeighborValue: stack ? 0 : undefined,
    xAxis: xAxisLabel,
    sortSeriesType,
    sortSeriesAscending,
    stack,
    totalStackedValues,
  });
  const rebasedDataB = rebaseForecastDatum(data2, verboseMap);
  const {
    totalStackedValues: totalStackedValuesB,
    thresholdValues: thresholdValuesB,
  } = extractDataTotalValues(rebasedDataB, {
    stack: Boolean(stackB),
    percentageThreshold,
    xAxisCol: xAxisLabel,
  });
  const [rawSeriesB, sortedTotalValuesB] = extractSeries(rebasedDataB, {
    fillNeighborValue: stackB ? 0 : undefined,
    xAxis: xAxisLabel,
    sortSeriesType: sortSeriesTypeB,
    sortSeriesAscending: sortSeriesAscendingB,
    stack: Boolean(stackB),
    totalStackedValues: totalStackedValuesB,
  });

  const dataTypes = getColtypesMapping(queriesData[0]);
  const xAxisDataType = dataTypes?.[xAxisLabel] ?? dataTypes?.[xAxisOrig];
  const xAxisType = getAxisType(stack, xAxisForceCategorical, xAxisDataType);
  const series: SeriesOption[] = [];
  const formatter = contributionMode
    ? getNumberFormatter(',.0%')
    : currencyFormat?.symbol
      ? new CurrencyFormatter({
          d3Format: yAxisFormat,
          currency: currencyFormat,
        })
      : getNumberFormatter(yAxisFormat);
  const formatterSecondary = contributionMode
    ? getNumberFormatter(',.0%')
    : currencyFormatSecondary?.symbol
      ? new CurrencyFormatter({
          d3Format: yAxisFormatSecondary,
          currency: currencyFormatSecondary,
        })
      : getNumberFormatter(yAxisFormatSecondary);
  const customFormatters = buildCustomFormatters(
    [...ensureIsArray(metrics), ...ensureIsArray(metricsB)],
    currencyFormats,
    columnFormats,
    yAxisFormat,
    currencyFormat,
  );
  const customFormattersSecondary = buildCustomFormatters(
    [...ensureIsArray(metrics), ...ensureIsArray(metricsB)],
    currencyFormats,
    columnFormats,
    yAxisFormatSecondary,
    currencyFormatSecondary,
  );

  const primarySeries = new Set<string>();
  const secondarySeries = new Set<string>();
  const mapSeriesIdToAxis = (
    seriesOption: SeriesOption,
    index?: number,
  ): void => {
    if (index === 1) {
      secondarySeries.add(seriesOption.id as string);
    } else {
      primarySeries.add(seriesOption.id as string);
    }
  };
  rawSeriesA.forEach(seriesOption =>
    mapSeriesIdToAxis(seriesOption, yAxisIndex),
  );
  rawSeriesB.forEach(seriesOption =>
    mapSeriesIdToAxis(seriesOption, yAxisIndexB),
  );
  const showValueIndexesA = extractShowValueIndexes(rawSeriesA, {
    stack,
    onlyTotal,
  });
  const showValueIndexesB = extractShowValueIndexes(rawSeriesB, {
    stack,
    onlyTotal,
  });

  annotationLayers
    .filter((layer: AnnotationLayer) => layer.show)
    .forEach((layer: AnnotationLayer) => {
      if (isFormulaAnnotationLayer(layer))
        series.push(
          transformFormulaAnnotation(
            layer,
            data1,
            xAxisLabel,
            xAxisType,
            colorScale,
            sliceId,
          ),
        );
      else if (isIntervalAnnotationLayer(layer)) {
        series.push(
          ...transformIntervalAnnotation(
            layer,
            data1,
            annotationData,
            colorScale,
            theme,
            sliceId,
          ),
        );
      } else if (isEventAnnotationLayer(layer)) {
        series.push(
          ...transformEventAnnotation(
            layer,
            data1,
            annotationData,
            colorScale,
            theme,
            sliceId,
          ),
        );
      } else if (isTimeseriesAnnotationLayer(layer)) {
        series.push(
          ...transformTimeseriesAnnotation(
            layer,
            markerSize,
            data1,
            annotationData,
            colorScale,
            sliceId,
          ),
        );
      }
    });

  // yAxisBounds need to be parsed to replace incompatible values with undefined
  const [xAxisMin, xAxisMax] = (xAxisBounds || []).map(parseAxisBound);
  let [yAxisMin, yAxisMax] = (yAxisBounds || []).map(parseAxisBound);
  let [minSecondary, maxSecondary] = (yAxisBoundsSecondary || []).map(
    parseAxisBound,
  );

  const array = ensureIsArray(chartProps.rawFormData?.time_compare);
  const inverted = invert(verboseMap);

  rawSeriesA.forEach(entry => {
    const entryName = String(entry.name || '');
    const seriesName = inverted[entryName] || entryName;
    const colorScaleKey = getOriginalSeries(seriesName, array);

    let displayName: string;

    if (groupby.length > 0) {
      // When we have groupby, format as "metric, dimension"
      const metricPart = showQueryIdentifiers
        ? `${MetricDisplayNameA} (Query A)`
        : MetricDisplayNameA;
      displayName = `${metricPart}, ${entryName}`;
    } else {
      // When no groupby, format as just the entry name with optional query identifier
      displayName = showQueryIdentifiers ? `${entryName} (Query A)` : entryName;
    }

    const seriesFormatter = getFormatter(
      customFormatters,
      formatter,
      metrics,
      labelMap?.[seriesName]?.[0],
      !!contributionMode,
    );

    const transformedSeries = transformSeries(
      {
        ...entry,
        id: `${displayName || ''}`,
      },
      colorScale,
      colorScaleKey,
      {
        area,
        markerEnabled,
        markerSize,
        areaOpacity: opacity,
        seriesType,
        showValue,
        onlyTotal,
        stack: Boolean(stack),
        stackIdSuffix: '\na',
        yAxisIndex,
        filterState,
        seriesKey: entry.name,
        sliceId,
        queryIndex: 0,
        formatter:
          seriesType === EchartsTimeseriesSeriesType.Bar
            ? getOverMaxHiddenFormatter({
                max: yAxisMax,
                formatter: seriesFormatter,
              })
            : seriesFormatter,
        totalStackedValues: sortedTotalValuesA,
        showValueIndexes: showValueIndexesA,
        thresholdValues,
        timeShiftColor,
      },
    );
    if (transformedSeries) series.push(transformedSeries);
  });

  rawSeriesB.forEach(entry => {
    const entryName = String(entry.name || '');
    const seriesEntry = inverted[entryName] || entryName;
    const seriesName = `${seriesEntry} (1)`;
    const colorScaleKey = getOriginalSeries(seriesEntry, array);

    let displayName: string;

    if (groupbyB.length > 0) {
      // When we have groupby, format as "metric, dimension"
      const metricPart = showQueryIdentifiers
        ? `${MetricDisplayNameB} (Query B)`
        : MetricDisplayNameB;
      displayName = `${metricPart}, ${entryName}`;
    } else {
      // When no groupby, format as just the entry name with optional query identifier
      displayName = showQueryIdentifiers ? `${entryName} (Query B)` : entryName;
    }

    const seriesFormatter = getFormatter(
      customFormattersSecondary,
      formatterSecondary,
      metricsB,
      labelMapB?.[seriesName]?.[0],
      !!contributionMode,
    );

    const transformedSeries = transformSeries(
      {
        ...entry,
        id: `${displayName || ''}`,
      },

      colorScale,
      colorScaleKey,
      {
        area: areaB,
        markerEnabled: markerEnabledB,
        markerSize: markerSizeB,
        areaOpacity: opacityB,
        seriesType: seriesTypeB,
        showValue: showValueB,
        onlyTotal: onlyTotalB,
        stack: Boolean(stackB),
        stackIdSuffix: '\nb',
        yAxisIndex: yAxisIndexB,
        filterState,
        seriesKey: entry.name,
        sliceId,
        queryIndex: 1,
        formatter:
          seriesTypeB === EchartsTimeseriesSeriesType.Bar
            ? getOverMaxHiddenFormatter({
                max: maxSecondary,
                formatter: seriesFormatter,
              })
            : seriesFormatter,
        totalStackedValues: sortedTotalValuesB,
        showValueIndexes: showValueIndexesB,
        thresholdValues: thresholdValuesB,
        timeShiftColor,
      },
    );
    if (transformedSeries) series.push(transformedSeries);
  });

  // default to 0-100% range when doing row-level contribution chart
  if (contributionMode === 'row' && stack) {
    if (yAxisMin === undefined) yAxisMin = 0;
    if (yAxisMax === undefined) yAxisMax = 1;
    if (minSecondary === undefined) minSecondary = 0;
    if (maxSecondary === undefined) maxSecondary = 1;
  }

  const tooltipFormatter =
    xAxisDataType === GenericDataType.Temporal
      ? getTooltipTimeFormatter(tooltipTimeFormat)
      : String;
  const xAxisFormatter =
    xAxisDataType === GenericDataType.Temporal
      ? getXAxisFormatter(xAxisTimeFormat)
      : String;

  const addYAxisTitleOffset = !!(yAxisTitle || yAxisTitleSecondary);
  const addXAxisTitleOffset = !!xAxisTitle;

  const chartPadding = getPadding(
    showLegend,
    legendOrientation,
    addYAxisTitleOffset,
    zoomable,
    null,
    addXAxisTitleOffset,
    yAxisTitlePosition,
    convertInteger(yAxisTitleMargin),
    convertInteger(xAxisTitleMargin),
  );

  const { setDataMask = () => {}, onContextMenu } = hooks;
  const alignTicks = yAxisIndex !== yAxisIndexB;

  const echartOptions: EChartsCoreOption = {
    useUTC: true,
    grid: {
      ...defaultGrid,
      ...chartPadding,
    },
    xAxis: {
      type: xAxisType,
      name: xAxisTitle,
      nameGap: convertInteger(xAxisTitleMargin),
      nameLocation: 'middle',
      axisLabel: {
        formatter: xAxisFormatter,
        rotate: xAxisLabelRotation,
        interval: xAxisLabelInterval,
      },
      minorTick: { show: minorTicks },
      minInterval:
        xAxisType === AxisType.Time && timeGrainSqla
          ? TIMEGRAIN_TO_TIMESTAMP[
              timeGrainSqla as keyof typeof TIMEGRAIN_TO_TIMESTAMP
            ]
          : 0,
      ...getMinAndMaxFromBounds(
        xAxisType,
        truncateXAxis,
        xAxisMin,
        xAxisMax,
        seriesType === EchartsTimeseriesSeriesType.Bar ||
          seriesTypeB === EchartsTimeseriesSeriesType.Bar
          ? EchartsTimeseriesSeriesType.Bar
          : undefined,
      ),
    },
    yAxis: [
      {
        ...defaultYAxis,
        type: logAxis ? 'log' : 'value',
        min: yAxisMin,
        max: yAxisMax,
        minorTick: { show: minorTicks },
        minorSplitLine: { show: minorSplitLine },
        axisLabel: {
          formatter: getYAxisFormatter(
            metrics,
            !!contributionMode,
            customFormatters,
            formatter,
            yAxisFormat,
          ),
        },
        scale: truncateYAxis,
        name: yAxisTitle,
        nameGap: convertInteger(yAxisTitleMargin),
        nameLocation: yAxisTitlePosition === 'Left' ? 'middle' : 'end',
        alignTicks,
      },
      {
        ...defaultYAxis,
        type: logAxisSecondary ? 'log' : 'value',
        min: minSecondary,
        max: maxSecondary,
        minorTick: { show: minorTicks },
        splitLine: { show: false },
        minorSplitLine: { show: minorSplitLine },
        axisLabel: {
          formatter: getYAxisFormatter(
            metricsB,
            !!contributionMode,
            customFormattersSecondary,
            formatterSecondary,
            yAxisFormatSecondary,
          ),
        },
        scale: truncateYAxis,
        name: yAxisTitleSecondary,
        alignTicks,
      },
    ],
    tooltip: {
      ...getDefaultTooltip(refs),
      show: !inContextMenu,
      trigger: richTooltip ? 'axis' : 'item',
      formatter: (params: any) => {
        const xValue: number = richTooltip
          ? params[0].value[0]
          : params.value[0];
        const forecastValue: any[] = richTooltip ? params : [params];

        const sortedKeys = extractTooltipKeys(
          forecastValue,
          // horizontal mode is not supported in mixed series chart
          1,
          richTooltip,
          tooltipSortByMetric,
        );

        const rows: string[][] = [];
        const forecastValues =
          extractForecastValuesFromTooltipParams(forecastValue);

        const keys = Object.keys(forecastValues);
        let focusedRow;
        sortedKeys
          .filter(key => keys.includes(key))
          .forEach(key => {
            const value = forecastValues[key];
            // if there are no dimensions, key is a verbose name of a metric,
            // otherwise it is a comma separated string where the first part is metric name
            let formatterKey;
            if (primarySeries.has(key)) {
              formatterKey =
                groupby.length === 0 ? inverted[key] : labelMap[key]?.[0];
            } else {
              formatterKey =
                groupbyB.length === 0 ? inverted[key] : labelMapB[key]?.[0];
            }
            const tooltipFormatter = getFormatter(
              customFormatters,
              formatter,
              metrics,
              formatterKey,
              !!contributionMode,
            );
            const tooltipFormatterSecondary = getFormatter(
              customFormattersSecondary,
              formatterSecondary,
              metricsB,
              formatterKey,
              !!contributionMode,
            );
            const row = formatForecastTooltipSeries({
              ...value,
              seriesName: key,
              formatter: primarySeries.has(key)
                ? tooltipFormatter
                : tooltipFormatterSecondary,
            });
            rows.push(row);
            if (key === focusedSeries) {
              focusedRow = rows.length - 1;
            }
          });
        return tooltipHtml(rows, tooltipFormatter(xValue), focusedRow);
      },
    },
    legend: {
      ...getLegendProps(
        legendType,
        legendOrientation,
        showLegend,
        theme,
        zoomable,
      ),
      // @ts-ignore
      data: series
        .filter(
          entry =>
            extractForecastSeriesContext((entry.name || '') as string).type ===
            ForecastSeriesEnum.Observation,
        )
        .map(entry => entry.id || entry.name || '')
        .concat(extractAnnotationLabels(annotationLayers, annotationData)),
    },
    series: dedupSeries(reorderForecastSeries(series) as SeriesOption[]),
    toolbox: {
      show: zoomable,
      top: TIMESERIES_CONSTANTS.toolboxTop,
      right: TIMESERIES_CONSTANTS.toolboxRight,
      feature: {
        dataZoom: {
          yAxisIndex: false,
          title: {
            zoom: 'zoom area',
            back: 'restore zoom',
          },
        },
      },
    },
    dataZoom: zoomable
      ? [
          {
            type: 'slider',
            start: TIMESERIES_CONSTANTS.dataZoomStart,
            end: TIMESERIES_CONSTANTS.dataZoomEnd,
            bottom: TIMESERIES_CONSTANTS.zoomBottom,
          },
        ]
      : [],
  };

  const onFocusedSeries = (seriesName: string | null) => {
    focusedSeries = seriesName;
  };

  return {
    formData,
    width,
    height,
    echartOptions,
    setDataMask,
    emitCrossFilters,
    labelMap,
    labelMapB,
    groupby,
    groupbyB,
    seriesBreakdown: rawSeriesA.length,
    selectedValues: filterState.selectedValues || [],
    onContextMenu,
    onFocusedSeries,
    xValueFormatter: tooltipFormatter,
    xAxis: {
      label: xAxisLabel,
      type: xAxisType,
    },
    refs,
    coltypeMapping,
  };
}
