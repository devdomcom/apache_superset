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
import { useMemo, useState } from 'react';
import { isFeatureEnabled, FeatureFlag, t } from '@superset-ui/core';
import {
  Actions,
  createErrorHandler,
  createFetchRelated,
} from 'src/views/CRUD/utils';
import { useListViewResource, useFavoriteStatus } from 'src/views/CRUD/hooks';
import {
  ConfirmStatusChange,
  Tooltip,
  FaveStar,
} from '@superset-ui/core/components';
import {
  Tag as AntdTag,
  ListView,
  ModifiedInfo,
  ListViewFilterOperator as FilterOperator,
  type ListViewFilters,
  type ListViewProps,
} from 'src/components';
import SubMenu, { SubMenuProps } from 'src/features/home/SubMenu';
import { dangerouslyGetItemDoNotUse } from 'src/utils/localStorageHelpers';
import withToasts from 'src/components/MessageToasts/withToasts';
import { Icons } from '@superset-ui/core/components/Icons';
import { Link } from 'react-router-dom';
import { deleteTags } from 'src/features/tags/tags';
import { QueryObjectColumns, Tag } from 'src/views/CRUD/types';
import TagModal from 'src/features/tags/TagModal';

const PAGE_SIZE = 25;

interface TagListProps {
  addDangerToast: (msg: string) => void;
  addSuccessToast: (msg: string) => void;
  user: {
    userId: string | number;
    firstName: string;
    lastName: string;
  };
}

function TagList(props: TagListProps) {
  const { addDangerToast, addSuccessToast, user } = props;
  const { userId } = user;

  const initialFilters = useMemo(
    () => [
      {
        id: 'type',
        operator: 'custom_tag',
        value: true,
      },
    ],
    [],
  );

  const {
    state: {
      loading,
      resourceCount: tagCount,
      resourceCollection: tags,
      bulkSelectEnabled,
    },
    hasPerm,
    fetchData,
    toggleBulkSelect,
    refreshData,
  } = useListViewResource<Tag>(
    'tag',
    t('tag'),
    addDangerToast,
    undefined,
    undefined,
    initialFilters,
  );

  const [showTagModal, setShowTagModal] = useState<boolean>(false);
  const [tagToEdit, setTagToEdit] = useState<Tag | null>(null);
  const tagIds = useMemo(() => tags.map(c => c.id), [tags]);
  const [saveFavoriteStatus, favoriteStatus] = useFavoriteStatus(
    'tag',
    tagIds,
    addDangerToast,
  );

  // TODO: Fix usage of localStorage keying on the user id
  const userKey = dangerouslyGetItemDoNotUse(userId?.toString(), null);

  const canDelete = hasPerm('can_write');
  const canEdit = hasPerm('can_write');

  const initialSort = [{ id: 'changed_on_delta_humanized', desc: true }];

  function handleTagsDelete(tags: Tag[]) {
    deleteTags(
      tags,
      (msg: string) => {
        addSuccessToast(msg);
        refreshData();
      },
      msg => {
        addDangerToast(msg);
        refreshData();
      },
    );
  }

  const handleTagEdit = (tag: Tag) => {
    setShowTagModal(true);
    setTagToEdit(tag);
  };

  const emptyState = {
    title: t('No Tags created'),
    image: 'dashboard.svg',
    description:
      'Create a new tag and assign it to existing entities like charts or dashboards',
    buttonAction: () => setShowTagModal(true),
    buttonIcon: <Icons.PlusOutlined iconSize="m" data-test="add-rule-empty" />,
    buttonText: t('Create a new Tag'),
  };

  const columns = useMemo(
    () => [
      {
        Cell: ({
          row: {
            original: { id },
          },
        }: any) =>
          userId && (
            <FaveStar
              itemId={id}
              saveFaveStar={saveFavoriteStatus}
              isStarred={favoriteStatus[id]}
            />
          ),
        Header: '',
        id: 'id',
        disableSortBy: true,
        size: 'xs',
        hidden: !userId,
      },
      {
        Cell: ({
          row: {
            original: { id, name: tagName },
          },
        }: any) => (
          <AntdTag>
            <Link to={`/superset/all_entities/?id=${id}`}>{tagName}</Link>
          </AntdTag>
        ),
        Header: t('Name'),
        accessor: 'name',
        id: 'name',
      },
      {
        Cell: ({
          row: {
            original: {
              changed_on_delta_humanized: changedOn,
              changed_by: changedBy,
            },
          },
        }: any) => <ModifiedInfo date={changedOn} user={changedBy} />,
        Header: t('Last modified'),
        accessor: 'changed_on_delta_humanized',
        size: 'xl',
        id: 'changed_on_delta_humanized',
      },
      {
        Cell: ({ row: { original } }: any) => {
          const handleEdit = () => handleTagEdit(original);
          return (
            <Actions className="actions">
              {canDelete && (
                <ConfirmStatusChange
                  title={t('Please confirm')}
                  description={
                    <>
                      {t('Are you sure you want to delete')}{' '}
                      <b>{original.dashboard_title}</b>?
                    </>
                  }
                  onConfirm={() => handleTagsDelete([original])}
                >
                  {confirmDelete => (
                    <Tooltip
                      id="delete-action-tooltip"
                      title={t('Delete')}
                      placement="bottom"
                    >
                      <span
                        role="button"
                        tabIndex={0}
                        className="action-button"
                        onClick={confirmDelete}
                      >
                        <Icons.DeleteOutlined
                          data-test="dashboard-list-trash-icon"
                          iconSize="l"
                        />
                      </span>
                    </Tooltip>
                  )}
                </ConfirmStatusChange>
              )}
              {canEdit && (
                <Tooltip
                  id="edit-action-tooltip"
                  title={t('Edit')}
                  placement="bottom"
                >
                  <span
                    role="button"
                    tabIndex={0}
                    className="action-button"
                    onClick={handleEdit}
                  >
                    <Icons.EditOutlined data-test="edit-alt" iconSize="l" />
                  </span>
                </Tooltip>
              )}
            </Actions>
          );
        },
        Header: t('Actions'),
        id: 'actions',
        hidden: !canDelete,
        disableSortBy: true,
      },
      {
        accessor: QueryObjectColumns.ChangedBy,
        hidden: true,
        id: QueryObjectColumns.ChangedBy,
      },
    ],
    [userId, canDelete, refreshData, addSuccessToast, addDangerToast],
  );

  const filters: ListViewFilters = useMemo(() => {
    const filters_list = [
      {
        Header: t('Name'),
        id: 'name',
        input: 'search',
        operator: FilterOperator.Contains,
      },
      {
        Header: t('Modified by'),
        key: 'changed_by',
        id: 'changed_by',
        input: 'select',
        operator: FilterOperator.RelationOneMany,
        unfilteredLabel: t('All'),
        fetchSelects: createFetchRelated(
          'tag',
          'changed_by',
          createErrorHandler(errMsg =>
            t(
              'An error occurred while fetching dataset datasource values: %s',
              errMsg,
            ),
          ),
          user,
        ),
        paginate: true,
      },
    ] as ListViewFilters;
    return filters_list;
  }, [addDangerToast, props.user]);

  const sortTypes = [
    {
      desc: false,
      id: 'name',
      label: t('Alphabetical'),
      value: 'alphabetical',
    },
    {
      desc: true,
      id: 'changed_on_delta_humanized',
      label: t('Recently modified'),
      value: 'recently_modified',
    },
    {
      desc: false,
      id: 'changed_on_delta_humanized',
      label: t('Least recently modified'),
      value: 'least_recently_modified',
    },
  ];

  const subMenuButtons: SubMenuProps['buttons'] = [];

  if (canDelete) {
    subMenuButtons.push({
      name: t('Bulk select'),
      buttonStyle: 'secondary',
      'data-test': 'bulk-select',
      onClick: toggleBulkSelect,
    });
  }

  // render new 'New Tag' btn
  subMenuButtons.push({
    icon: <Icons.PlusOutlined iconSize="m" />,
    name: t('Tag'),
    buttonStyle: 'primary',
    'data-test': 'bulk-select',
    onClick: () => setShowTagModal(true),
  });

  const handleBulkDelete = (tagsToDelete: Tag[]) =>
    handleTagsDelete(tagsToDelete);

  return (
    <>
      <TagModal
        show={showTagModal}
        onHide={() => {
          setShowTagModal(false);
          setTagToEdit(null);
        }}
        editTag={tagToEdit}
        refreshData={refreshData}
        addSuccessToast={addSuccessToast}
        addDangerToast={addDangerToast}
        clearOnHide
      />
      <SubMenu name={t('Tags')} buttons={subMenuButtons} />
      <ConfirmStatusChange
        title={t('Please confirm')}
        description={t('Are you sure you want to delete the selected tags?')}
        onConfirm={handleBulkDelete}
      >
        {confirmDelete => {
          const bulkActions: ListViewProps['bulkActions'] = [];
          if (canDelete) {
            bulkActions.push({
              key: 'delete',
              name: t('Delete'),
              type: 'danger',
              onSelect: confirmDelete,
            });
          }
          return (
            <>
              <ListView<Tag>
                bulkActions={bulkActions}
                bulkSelectEnabled={bulkSelectEnabled}
                cardSortSelectOptions={sortTypes}
                className="tags-list-view"
                columns={columns}
                count={tagCount}
                data={tags}
                disableBulkSelect={toggleBulkSelect}
                refreshData={refreshData}
                emptyState={emptyState}
                fetchData={fetchData}
                filters={filters}
                initialSort={initialSort}
                loading={loading}
                addDangerToast={addDangerToast}
                addSuccessToast={addSuccessToast}
                pageSize={PAGE_SIZE}
                showThumbnails={
                  userKey
                    ? userKey.thumbnails
                    : isFeatureEnabled(FeatureFlag.Thumbnails)
                }
                defaultViewMode={
                  isFeatureEnabled(FeatureFlag.ListviewsDefaultCardView)
                    ? 'card'
                    : 'table'
                }
              />
            </>
          );
        }}
      </ConfirmStatusChange>
    </>
  );
}

export default withToasts(TagList);
