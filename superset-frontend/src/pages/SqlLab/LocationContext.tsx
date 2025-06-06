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

import { createContext, useContext, FC, ReactNode } from 'react';

import { useLocation } from 'react-router-dom';

export type LocationState = {
  requestedQuery?: Record<string, any>;
  isDataset?: boolean;
};

export const locationContext = createContext<LocationState>({});
const { Provider } = locationContext;

const EMPTY_STATE: LocationState = {};

export const LocationProvider: FC = ({ children }: { children: ReactNode }) => {
  const location = useLocation<LocationState>();
  if (location.state) {
    return <Provider value={location.state}>{children}</Provider>;
  }
  const queryParams = new URLSearchParams(location.search);
  if (queryParams.size > 0) {
    const dbid = queryParams.get('dbid');
    const sql = queryParams.get('sql');
    const name = queryParams.get('name');
    const schema = queryParams.get('schema');
    const autorun = queryParams.get('autorun') === 'true';

    const queryParamsState = {
      requestedQuery: { dbid, sql, name, schema, autorun },
      isDataset: true,
    } as LocationState;
    return <Provider value={queryParamsState}>{children}</Provider>;
  }

  return <Provider value={EMPTY_STATE}>{children}</Provider>;
};
export const useLocationState = () => useContext(locationContext);
